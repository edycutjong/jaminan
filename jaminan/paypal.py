"""PayPal REST client — every call Jaminan makes to PayPal goes through here.

Surfaces: Orders v2 (AUTHORIZE with vault consent, merchant-initiated orders on a vault_id, tracking),
Payments v2 authorizations (capture with final_capture, void, reauthorize, read-back), Vault v3
(payment-token delete), Invoicing v2 (create, send, QR), Reporting v1 (Transaction Search),
Notifications v1 (webhook signature verification, webhook registration).

Every write carries a deterministic PayPal-Request-Id (invariant I4) so a retried request can never
double-capture, and every call is handed to `on_call` with its PayPal-Debug-Id for the public ledger.
Sandbox only: Settings refuses a non-sandbox base URL.
"""
from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import httpx


def request_id(*parts: Any) -> str:
    """I4: PayPal-Request-Id = sha256(authorization_id|action|amount)[:32] (or rental id for order creation)."""
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


def money(cents: int, currency: str = "USD") -> dict[str, str]:
    return {"currency_code": currency, "value": f"{cents / 100:.2f}"}


def cents(value: str | float) -> int:
    return int(round(float(value) * 100))


@dataclass
class Resp:
    status: int
    body: dict[str, Any]
    debug_id: str | None
    action: str
    request_id: str | None = None
    ms: int = 0

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def issue(self) -> str | None:
        details = self.body.get("details") or []
        if details:
            return details[0].get("issue")
        return self.body.get("name")


class PayPalError(RuntimeError):
    def __init__(self, resp: Resp):
        self.resp = resp
        super().__init__(f"PayPal {resp.action} -> {resp.status} {resp.issue} (debug {resp.debug_id})")


@dataclass
class PayPal:
    base: str
    client_id: str
    client_secret: str
    on_call: Callable[[dict[str, Any]], None] | None = None
    timeout: float = 30.0
    _token: str | None = field(default=None, repr=False)
    _token_exp: float = 0.0

    def __post_init__(self) -> None:
        if "sandbox" not in self.base:
            raise RuntimeError("refusing to run against a non-sandbox PayPal base URL")
        self.http = httpx.Client(base_url=self.base, timeout=self.timeout)

    # -- transport ------------------------------------------------------------------------------
    def token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        r = self.http.post("/v1/oauth2/token", data={"grant_type": "client_credentials"},
                           headers={"Authorization": f"Basic {basic}"})
        r.raise_for_status()
        j = r.json()
        self._token, self._token_exp = j["access_token"], time.time() + int(j.get("expires_in", 3000))
        return self._token

    def call(self, method: str, path: str, action: str, body: dict | None = None, *, rid: str | None = None,
             rental_id: str | None = None, object_id: str | None = None, prefer: str = "return=representation",
             params: dict | None = None, retries: int = 2) -> Resp:
        headers = {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json", "Prefer": prefer}
        if rid:
            headers["PayPal-Request-Id"] = rid
        content = None
        if body is not None:
            import json as _json
            content = _json.dumps(body)
        elif method == "POST":
            content = "{}"
        attempt = 0
        while True:
            t0 = time.perf_counter()
            try:
                r = self.http.request(method, path, content=content, headers=headers, params=params)
                status, debug = r.status_code, r.headers.get("Paypal-Debug-Id")
                try:
                    data = r.json() if r.content else {}
                except ValueError:
                    data = {"raw": r.text[:500]}
            except httpx.TransportError as e:  # upstream down: retry with the SAME request id (I4)
                status, debug, data = 599, None, {"name": "TRANSPORT_ERROR", "message": str(e)}
            ms = int((time.perf_counter() - t0) * 1000)
            # 5xx / transport → retry with the same PayPal-Request-Id; writes stay idempotent
            if status >= 500 and attempt < retries and (rid or method == "GET"):
                attempt += 1
                time.sleep(0.6 * attempt)
                continue
            break
        resp = Resp(status, data if isinstance(data, dict) else {"items": data}, debug, action, rid, ms)
        if self.on_call:
            oid = object_id or (resp.body.get("id") if isinstance(resp.body, dict) else None)
            self.on_call({"rental_id": rental_id, "action": action, "method": method, "path": path,
                          "request_id": rid, "http_status": status, "debug_id": debug, "object_id": oid,
                          "issue": None if resp.ok else resp.issue, "ms": ms,
                          "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        return resp

    # -- Orders v2 -----------------------------------------------------------------------------
    def create_authorize_order(self, rental_id: str, amount_cents: int, description: str, return_url: str,
                               cancel_url: str, brand: str = "Jaminan") -> Resp:
        """S1: ONE renter approval → AUTHORIZE fee + deposit, with vault consent for later MIT charges."""
        body = {
            "intent": "AUTHORIZE",
            "purchase_units": [{"reference_id": rental_id, "custom_id": rental_id, "description": description[:127],
                                "amount": money(amount_cents)}],
            "payment_source": {"paypal": {
                "experience_context": {"return_url": return_url, "cancel_url": cancel_url, "user_action": "CONTINUE",
                                       "shipping_preference": "NO_SHIPPING", "brand_name": brand,
                                       "landing_page": "LOGIN"},
                "attributes": {"vault": {"store_in_vault": "ON_SUCCESS", "usage_type": "MERCHANT",
                                         "customer_type": "CONSUMER"}}}},
        }
        return self.call("POST", "/v2/checkout/orders", "order.create", body,
                         rid=request_id(rental_id, "order.create", amount_cents), rental_id=rental_id)

    def get_order(self, order_id: str, rental_id: str | None = None) -> Resp:
        return self.call("GET", f"/v2/checkout/orders/{order_id}", "order.get", rental_id=rental_id, object_id=order_id)

    def authorize_order(self, order_id: str, rental_id: str | None = None) -> Resp:
        return self.call("POST", f"/v2/checkout/orders/{order_id}/authorize", "order.authorize",
                         rid=request_id(order_id, "order.authorize", 0), rental_id=rental_id, object_id=order_id)

    def create_vault_order(self, ref: str, vault_id: str, amount_cents: int, intent: str, description: str,
                           rental_id: str | None = None) -> Resp:
        """S4/S5: merchant-initiated order on a saved PayPal wallet (no buyer approval)."""
        body = {"intent": intent,
                "purchase_units": [{"reference_id": ref, "custom_id": ref, "description": description[:127],
                                    "amount": money(amount_cents)}],
                "payment_source": {"paypal": {"vault_id": vault_id}}}
        return self.call("POST", "/v2/checkout/orders", f"order.create.mit.{intent.lower()}", body,
                         rid=request_id(ref, f"mit.{intent}", amount_cents, vault_id), rental_id=rental_id)

    def add_tracking(self, order_id: str, capture_id: str, tracking_number: str, rental_id: str | None = None,
                     notify_payer: bool = False) -> Resp:
        """S6: handover record — tracking on the fee capture; the number carries the baseline hash prefix."""
        body = {"capture_id": capture_id, "tracking_number": tracking_number, "carrier": "OTHER",
                "carrier_name_other": "Local pickup (Jaminan handover)", "notify_payer": notify_payer}
        return self.call("POST", f"/v2/checkout/orders/{order_id}/track", "order.track", body,
                         rid=request_id(capture_id, "track", tracking_number), rental_id=rental_id, object_id=order_id)

    # -- Payments v2: authorizations -------------------------------------------------------------
    def capture(self, authorization_id: str, amount_cents: int, final_capture: bool, invoice_id: str,
                note: str, rental_id: str | None = None, action: str | None = None) -> Resp:
        action = action or ("auth.capture.final" if final_capture else "auth.capture.partial")
        body = {"amount": money(amount_cents), "final_capture": final_capture, "invoice_id": invoice_id[:127],
                "note_to_payer": note[:255]}
        return self.call("POST", f"/v2/payments/authorizations/{authorization_id}/capture", action, body,
                         rid=request_id(authorization_id, action, amount_cents), rental_id=rental_id)

    def void(self, authorization_id: str, rental_id: str | None = None) -> Resp:
        return self.call("POST", f"/v2/payments/authorizations/{authorization_id}/void", "auth.void",
                         rid=request_id(authorization_id, "auth.void", 0), rental_id=rental_id,
                         object_id=authorization_id, prefer="return=representation")

    def reauthorize(self, authorization_id: str, amount_cents: int, rental_id: str | None = None) -> Resp:
        return self.call("POST", f"/v2/payments/authorizations/{authorization_id}/reauthorize", "auth.reauthorize",
                         {"amount": money(amount_cents)},
                         rid=request_id(authorization_id, "auth.reauthorize", amount_cents), rental_id=rental_id)

    def get_authorization(self, authorization_id: str, rental_id: str | None = None) -> Resp:
        return self.call("GET", f"/v2/payments/authorizations/{authorization_id}", "auth.get",
                         rental_id=rental_id, object_id=authorization_id)

    def get_capture(self, capture_id: str, rental_id: str | None = None) -> Resp:
        return self.call("GET", f"/v2/payments/captures/{capture_id}", "capture.get", rental_id=rental_id,
                         object_id=capture_id)

    # -- Vault v3 --------------------------------------------------------------------------------
    def delete_payment_token(self, token_id: str, rental_id: str | None = None) -> Resp:
        return self.call("DELETE", f"/v3/vault/payment-tokens/{token_id}", "vault.delete", rental_id=rental_id,
                         object_id=token_id)

    def get_payment_token(self, token_id: str, rental_id: str | None = None) -> Resp:
        return self.call("GET", f"/v3/vault/payment-tokens/{token_id}", "vault.get", rental_id=rental_id,
                         object_id=token_id)

    # -- Invoicing v2 ----------------------------------------------------------------------------
    def create_invoice(self, rental_id: str, invoice_number: str, payer_email: str | None,
                       items: list[dict[str, Any]], note: str) -> Resp:
        detail = {"currency_code": "USD", "invoice_number": invoice_number[:25], "note": note[:4000],
                  "payment_term": {"term_type": "DUE_ON_RECEIPT"}}
        body: dict[str, Any] = {"detail": detail, "items": items}
        if payer_email:
            body["primary_recipients"] = [{"billing_info": {"email_address": payer_email}}]
        return self.call("POST", "/v2/invoicing/invoices", "invoice.create", body,
                         rid=request_id(rental_id, "invoice.create", invoice_number), rental_id=rental_id)

    def send_invoice(self, invoice_id: str, rental_id: str | None = None) -> Resp:
        return self.call("POST", f"/v2/invoicing/invoices/{invoice_id}/send", "invoice.send",
                         {"send_to_invoicer": False, "send_to_recipient": True},
                         rid=request_id(invoice_id, "invoice.send", 0), rental_id=rental_id, object_id=invoice_id)

    def invoice_qr(self, invoice_id: str, rental_id: str | None = None) -> Resp:
        return self.call("POST", f"/v2/invoicing/invoices/{invoice_id}/generate-qr-code", "invoice.qr",
                         {"width": 300, "height": 300}, rental_id=rental_id, object_id=invoice_id)

    def get_invoice(self, invoice_id: str, rental_id: str | None = None) -> Resp:
        return self.call("GET", f"/v2/invoicing/invoices/{invoice_id}", "invoice.get", rental_id=rental_id,
                         object_id=invoice_id)

    # -- Reporting v1 ----------------------------------------------------------------------------
    def transactions(self, start: str, end: str, page: int = 1) -> Resp:
        return self.call("GET", "/v1/reporting/transactions", "reporting.transactions",
                         params={"start_date": start, "end_date": end, "fields": "transaction_info",
                                 "page_size": 500, "page": page})

    # -- Notifications v1 ------------------------------------------------------------------------
    def verify_webhook(self, headers: dict[str, str], event: dict[str, Any], webhook_id: str) -> Resp:
        h = {k.lower(): v for k, v in headers.items()}
        body = {"auth_algo": h.get("paypal-auth-algo"), "cert_url": h.get("paypal-cert-url"),
                "transmission_id": h.get("paypal-transmission-id"), "transmission_sig": h.get("paypal-transmission-sig"),
                "transmission_time": h.get("paypal-transmission-time"), "webhook_id": webhook_id,
                "webhook_event": event}
        return self.call("POST", "/v1/notifications/verify-webhook-signature", "webhook.verify", body,
                         object_id=event.get("id"))

    def list_webhooks(self) -> Resp:
        return self.call("GET", "/v1/notifications/webhooks", "webhook.list")

    def create_webhook(self, url: str, events: list[str]) -> Resp:
        return self.call("POST", "/v1/notifications/webhooks", "webhook.create",
                         {"url": url, "event_types": [{"name": e} for e in events]})


# -- response helpers ------------------------------------------------------------------------------
def first_authorization(order_body: dict[str, Any]) -> dict[str, Any] | None:
    pu = (order_body.get("purchase_units") or [{}])[0]
    auths = (pu.get("payments") or {}).get("authorizations") or []
    return auths[0] if auths else None


def first_capture(order_body: dict[str, Any]) -> dict[str, Any] | None:
    pu = (order_body.get("purchase_units") or [{}])[0]
    caps = (pu.get("payments") or {}).get("captures") or []
    return caps[0] if caps else None


def vault_of(order_body: dict[str, Any]) -> dict[str, Any]:
    return (((order_body.get("payment_source") or {}).get("paypal") or {}).get("attributes") or {}).get("vault") or {}


def payer_email(order_body: dict[str, Any]) -> str | None:
    return ((order_body.get("payment_source") or {}).get("paypal") or {}).get("email_address") or \
        (order_body.get("payer") or {}).get("email_address")


def approve_link(order_body: dict[str, Any]) -> str | None:
    return next((l["href"] for l in order_body.get("links", []) if l.get("rel") in ("payer-action", "approve")), None)


def from_settings(s, on_call=None) -> PayPal:
    return PayPal(s.paypal_base, s.paypal_client_id, s.paypal_client_secret, on_call=on_call)

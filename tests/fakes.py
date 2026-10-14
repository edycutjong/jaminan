"""Test doubles: an in-memory PayPal that enforces the authorization rules the sandbox enforces, and a
scripted vision model. Used for fast service tests; the real-sandbox tests live in test_*_sandbox.py."""
from __future__ import annotations

import io
import re
import uuid

import numpy as np
from PIL import Image

from jaminan.paypal import PayPal, Resp
from jaminan.vision import Call, ClaimAnswer, CloseupLocation, MarkList, TicketRead


class FakePayPal(PayPal):
    def __init__(self):
        super().__init__("https://api-m.sandbox.paypal.com", "id", "secret")
        self.auths: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.seen: dict[str, Resp] = {}
        self.fail_next: list[int] = []

    def token(self) -> str:
        return "t"

    def _send(self, method, path, content, headers, params):
        import json
        rid = headers.get("PayPal-Request-Id")
        if rid and rid in self.seen:
            return self.seen[rid]
        status, data = self._route(method, path, json.loads(content) if content else {})
        out = (status, data, f"dbg-{uuid.uuid4().hex[:8]}")
        if rid and 200 <= status < 300:
            self.seen[rid] = out
        return out

    def _auth(self, amount):
        aid = uuid.uuid4().hex[:17].upper()
        self.auths[aid] = {"id": aid, "status": "CREATED", "amount": int(round(float(amount) * 100)), "captured": 0,
                           "expiration_time": "2026-11-12T00:00:00Z"}
        return self.auths[aid]

    def _route(self, method, path, body):
        if self.fail_next:
            return self.fail_next.pop(0), {"name": "INTERNAL_SERVER_ERROR"}
        if path == "/v2/checkout/orders" and method == "POST":
            oid = uuid.uuid4().hex[:17].upper()
            amount = body["purchase_units"][0]["amount"]["value"]
            src = body["payment_source"]["paypal"]
            if "vault_id" in src:
                if src["vault_id"].startswith("bad"):
                    return 422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "PAYMENT_SOURCE_DECLINED"}]}
                if body["intent"] == "AUTHORIZE":
                    a = self._auth(amount)
                    return 201, {"id": oid, "status": "COMPLETED",
                                 "purchase_units": [{"payments": {"authorizations": [dict(a)]}}]}
                return 201, {"id": oid, "status": "COMPLETED",
                             "purchase_units": [{"payments": {"captures": [{"id": "CAP" + oid[:8], "status": "COMPLETED"}]}}]}
            self.orders[oid] = {"status": "APPROVED", "amount": amount}
            return 201, {"id": oid, "status": "PAYER_ACTION_REQUIRED",
                         "links": [{"rel": "payer-action", "href": f"https://www.sandbox.paypal.com/checkoutnow?token={oid}"}]}
        m = re.match(r"/v2/checkout/orders/(\w+)(/authorize|/track)?$", path)
        if m:
            oid, tail = m.groups()
            if tail == "/authorize":
                a = self._auth(self.orders[oid]["amount"])
                return 201, {"id": oid, "status": "COMPLETED", "payment_source": {"paypal": {
                    "email_address": "buyer@example.com",
                    "attributes": {"vault": {"id": "vault-1", "status": "VAULTED", "customer": {"id": "cust-1"}}}}},
                    "purchase_units": [{"payments": {"authorizations": [dict(a)]}}]}
            if tail == "/track":
                return 201, {"id": oid}
            return 200, {"id": oid, "status": self.orders[oid]["status"]}
        m = re.match(r"/v2/payments/authorizations/(\w+)(/capture|/void|/reauthorize)?$", path)
        if m:
            aid, tail = m.groups()
            a = self.auths[aid]
            if tail is None:
                return 200, dict(a)
            if tail == "/void":
                if a["status"] in ("CAPTURED", "VOIDED"):
                    return 422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "AUTHORIZATION_ALREADY_" + a["status"]}]}
                a["status"] = "VOIDED"
                return 200, dict(a)
            if tail == "/reauthorize":
                return 422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "REAUTHORIZATION_TOO_SOON"}]}
            amt = int(round(float(body["amount"]["value"]) * 100))
            if a["status"] in ("CAPTURED", "VOIDED"):
                return 422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "AUTHORIZATION_ALREADY_CAPTURED"}]}
            if a["captured"] + amt > a["amount"]:
                return 422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "MAX_CAPTURE_AMOUNT_EXCEEDED"}]}
            a["captured"] += amt
            a["status"] = "CAPTURED" if body.get("final_capture") else "PARTIALLY_CAPTURED"
            return 201, {"id": "CAP" + uuid.uuid4().hex[:10].upper(), "status": "COMPLETED"}
        if path == "/v2/invoicing/invoices":
            return 201, {"id": "INV2-" + uuid.uuid4().hex[:8].upper(), "status": "DRAFT"}
        if path.endswith("/send"):
            return 200, {"links": [{"rel": "payer-view", "href": "https://www.sandbox.paypal.com/invoice/p/#x"}]}
        if path.endswith("/generate-qr-code"):
            return 200, {"raw": "iVBORw0KGgo="}
        m = re.match(r"/v2/payments/captures/(\w+)$", path)
        if m:
            return 200, {"id": m.group(1), "status": "COMPLETED"}
        if path.startswith("/v3/vault/payment-tokens/"):
            return 204, {}
        if path == "/v1/reporting/transactions":
            return 200, {"transaction_details": []}
        return 404, {"name": "RESOURCE_NOT_FOUND"}


class ScriptedVision:
    """Returns scripted answers. `model` is the id it claims to be served by."""

    def __init__(self, model="qwen-bench-pinned", claims=None, suggestions=None, premarks=None, fail=False):
        self.model, self.claims, self.suggestions, self.premarks = model, claims or {}, suggestions or {}, premarks or {}
        self.fail = fail
        self.calls = []

    def _call(self, parsed):
        if self.fail:
            return Call(False, None, None, None, 5, "timeout/transport: scripted")
        return Call(True, parsed, self.model, f"req-{len(self.calls)}", 5)

    def claim(self, return_crop, pickup_area, closeups, part, damage_class, angle):
        self.calls.append(("claim", angle, part, damage_class, len(closeups)))
        a = self.claims.get((angle, part, damage_class), {})
        base = {"mark_at_return": True, "class_consistent": True, "visible_at_pickup": False, "pickup_comparable": True,
                "same_view": True, "pickup_bbox": [400, 400, 100, 100], "closeup_located": None, "confidence": 0.9,
                "rationale": "scripted"}
        return self._call(ClaimAnswer.model_validate({**base, **a}))

    def suggest(self, pickup, ret, angle, baseline):
        self.calls.append(("suggest", angle))
        return self._call(MarkList.model_validate({"marks": self.suggestions.get(angle, [])}))

    def premark(self, pickup, angle):
        self.calls.append(("premark", angle))
        return self._call(MarkList.model_validate({"marks": self.premarks.get(angle, [])}))

    def locate_closeup(self, frame, closeup, angle):
        return self._call(CloseupLocation(located=True, bbox=[300, 300, 200, 200], confidence=0.8))

    def read_ticket(self, image, keys):
        return self._call(TicketRead(plate="B 0000 JMN", time="2099-01-01T00:00:00+07:00", violation=keys[0],
                                     amount_idr=250000, confidence=0.9))


def frame_bytes(seed: int, glare_box=None) -> bytes:
    """A synthetic sharp test pattern (NOT a scooter photo): exercises the gate and storage only."""
    rng = np.random.default_rng(seed)
    small = rng.integers(40, 200, size=(120, 160, 3)).astype(np.uint8)
    arr = np.asarray(Image.fromarray(small).resize((1280, 960), Image.NEAREST)).copy()
    if glare_box:
        x, y, w, h = glare_box
        arr[y:y + h, x:x + w] = 255
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "JPEG", quality=90)
    return buf.getvalue()

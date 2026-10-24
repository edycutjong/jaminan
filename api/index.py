"""Jaminan API — FastAPI, served as a Vercel Python function under /api/*."""
from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, File, Form, Header, Request, UploadFile  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from jaminan import gate, paypal, store, tariff, vision  # noqa: E402
from jaminan.config import Settings, load_local_env  # noqa: E402
from jaminan.rules import IllegalTransition  # noqa: E402
from jaminan.service import Service, ServiceError, iso, same_secret  # noqa: E402

if not os.environ.get("VERCEL"):
    load_local_env()

app = FastAPI(title="Jaminan API", docs_url="/api/docs", openapi_url="/api/openapi.json")
_svc: Service | None = None


def svc() -> Service:
    global _svc
    if _svc is None:
        s = Settings()
        _svc = Service(s, store.from_settings(s), paypal.from_settings(s), vision.from_settings(s))
    return _svc


@app.exception_handler(ServiceError)
async def service_error(_: Request, e: ServiceError):
    return JSONResponse({"error": e.code, "message": e.message, **e.extra}, status_code=e.status)


@app.exception_handler(IllegalTransition)
async def illegal_transition(_: Request, e: IllegalTransition):
    # a repeated tap (RETURNED → RETURNED) is a conflict to show, not a crash
    return JSONResponse({"error": "ILLEGAL_TRANSITION", "message": str(e)}, status_code=409)


@app.exception_handler(RequestValidationError)
async def bad_request(_: Request, e: RequestValidationError):
    # the same {error, message} shape as every other refusal, so the client never prints "[object Object]"
    msg = "; ".join(f"{'.'.join(str(x) for x in err.get('loc', [])[1:]) or 'body'}: {err.get('msg')}" for err in e.errors())
    return JSONResponse({"error": "BAD_REQUEST", "message": msg}, status_code=422)


Key = Header(default=None, alias="X-Jaminan-Key")
MAX_UPLOAD = 4_000_000

# Handlers that touch Pillow, Redis, PayPal or Qwen are plain `def`: FastAPI runs them in its thread pool, so one slow
# upload never blocks the event loop the other requests on this instance share.


def read_upload(file: UploadFile) -> bytes:
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise ServiceError(413, "TOO_LARGE", "frames are resized on the phone first; max 4 MB")
    return data


def client_ip(req: Request) -> str:
    return (req.headers.get("x-forwarded-for") or (req.client.host if req.client else "?")).split(",")[0].strip()


# ---------------------------------------------------------------------------------------------
@app.get("/api/health")
def health():
    s = svc().s
    return {"ok": True, "paypal": "sandbox" if "sandbox" in s.paypal_base else "?", "vision_model": s.vision_model,
            "benchmarked_model": s.benchmarked_model or None, "store": type(svc().db).__name__,
            "judge_pool": len(s.judge_vault_ids), "staged_set": svc().staged_manifest() is not None, "at": iso()}


@app.get("/api/shops/{shop_id}")
def shop(shop_id: str):
    sh = tariff.shops().get(shop_id)
    if not sh:
        raise ServiceError(404, "NO_SHOP", shop_id)
    return {"shop": sh, "vehicles": [v for v in tariff.vehicles().values() if v["shop_id"] == shop_id],
            "tariff": tariff.load("tv1").public()}


class NewRental(BaseModel):
    vehicle_id: str
    days: int = 1


@app.post("/api/shops/{shop_id}/rentals")
def new_rental(shop_id: str, body: NewRental):
    r = svc().create_rental(shop_id, body.vehicle_id, body.days)
    return {**svc().view(r, "shop"), "shop_key": r["keys"]["shop"]}


@app.get("/api/shops/{shop_id}/rentals")
def shop_rentals(shop_id: str):
    out = []
    for r in svc().shop_rentals(shop_id):
        out.append({k: r.get(k) for k in ("id", "kind", "state", "vehicle_label", "plate", "fee_cents", "deposit_cents",
                                          "created_at", "picked_up_at", "returned_at", "auth_status", "settlement",
                                          "tracking_number", "authorization_id")})
    return {"rentals": out}


@app.get("/api/rentals/{rid}")
def get_rental(rid: str, key: str | None = Key):
    s = svc()
    r = s.get(rid)
    role = s.role_of(r, key)
    if not role:  # payer email, plate and photos are only for the two parties
        raise ServiceError(403, "FORBIDDEN", "open this rental from the shop's QR (renter) or the shop phone")
    return s.view(r, role)


def _v(rid: str, key: str | None) -> dict:
    s = svc()
    r = s.get(rid)
    return s.view(r, s.role_of(r, key))


@app.post("/api/rentals/{rid}/approve")
def approve(rid: str, key: str | None = Key):
    s = svc()
    s.auth(s.get(rid), key, "renter")
    return s.approve(rid)


@app.post("/api/rentals/{rid}/authorize")
def authorize(rid: str, key: str | None = Key):
    s = svc()
    s.auth(s.get(rid), key, "renter")
    r = s.authorize(rid)
    if r.get("kind") == "judge_full" and r["state"] == "APPROVED":
        s.clone_staged(rid)
    return _v(rid, key)


@app.post("/api/rentals/{rid}/photos")
def photo(rid: str, phase: str = Form(...), angle: int = Form(...), file: UploadFile = File(...),
          key: str | None = Key):
    return svc().add_photo(rid, key, phase, angle, read_upload(file))


@app.post("/api/rentals/{rid}/baseline/premark")
def premark(rid: str, key: str | None = Key):
    svc().premark(rid, key)
    return _v(rid, key)


class MarkEdit(BaseModel):
    action: str
    mark: dict[str, Any]


@app.post("/api/rentals/{rid}/baseline/marks")
def marks(rid: str, body: MarkEdit, key: str | None = Key):
    svc().edit_mark(rid, key, body.action, body.mark)
    return _v(rid, key)


class Retake(BaseModel):
    angle: int
    reason: str = "low comparability"


@app.post("/api/rentals/{rid}/baseline/retake")
def retake(rid: str, body: Retake, key: str | None = Key):
    svc().request_retake(rid, key, body.angle, body.reason)
    return _v(rid, key)


@app.post("/api/rentals/{rid}/baseline/confirm")
def confirm(rid: str, key: str | None = Key):
    svc().confirm_baseline(rid, key)
    return _v(rid, key)


@app.post("/api/rentals/{rid}/return/complete")
def return_complete(rid: str, key: str | None = Key):
    svc().complete_return(rid, key)
    return _v(rid, key)


@app.post("/api/rentals/{rid}/return/suggest")
def suggest(rid: str, key: str | None = Key):
    svc().suggest(rid, key)
    return _v(rid, key)


@app.post("/api/rentals/{rid}/suggestions/{sid}/dismiss")
def dismiss(rid: str, sid: str, key: str | None = Key):
    svc().dismiss_suggestion(rid, key, sid)
    return _v(rid, key)


class Claim(BaseModel):
    angle: int
    bbox: list[float]
    part: str
    damage_class: str
    suggestion_id: str | None = None


@app.post("/api/rentals/{rid}/claims")
def claim(rid: str, body: Claim, key: str | None = Key):
    out = svc().claim(rid, key, body.angle, body.bbox, body.part, body.damage_class, body.suggestion_id)
    return {**out, "rental": _v(rid, key)}


@app.post("/api/rentals/{rid}/propose")
def propose(rid: str, key: str | None = Key):
    svc().propose(rid, key)
    return _v(rid, key)


class LineDecision(BaseModel):
    decision: str


@app.post("/api/rentals/{rid}/lines/{line_id}/decision")
def decision(rid: str, line_id: str, body: LineDecision, key: str | None = Key):
    svc().decide_line(rid, key, line_id, body.decision)
    return _v(rid, key)


@app.post("/api/rentals/{rid}/settle")
def settle(rid: str, key: str | None = Key):
    svc().settle(rid, key)
    return _v(rid, key)


@app.post("/api/rentals/{rid}/release")
def release(rid: str, key: str | None = Key):
    svc().release(rid, key)
    return _v(rid, key)


@app.delete("/api/rentals/{rid}/vault")
def revoke(rid: str, key: str | None = Key):
    svc().revoke_vault(rid, key)
    return _v(rid, key)


@app.get("/api/rentals/{rid}/evidence")
def evidence(rid: str, t: str | None = None, key: str | None = Key):
    return svc().evidence(rid, key, t)


@app.post("/api/rentals/{rid}/fines")
def fine(rid: str, ticket_amount_idr: int = Form(..., gt=0, le=100_000_000), file: UploadFile = File(...),
         key: str | None = Key):
    return svc().create_fine(rid, key, read_upload(file), ticket_amount_idr)


@app.get("/api/rentals/{rid}/fines")
def fines(rid: str, key: str | None = Key):
    r = svc().get(rid)
    if not svc().role_of(r, key):
        raise ServiceError(403, "FORBIDDEN", "fines are shown to the renter and the shop")
    return {"fines": [x for x in svc().db.mget_json([f"fine:{f}" for f in r.get("fines", [])]) if x]}


@app.post("/api/rentals/{rid}/fines/{fid}/contest")
def contest(rid: str, fid: str, key: str | None = Key):
    return svc().contest_fine(rid, key, fid)


@app.get("/api/frames/{sha}")
def frame(sha: str, bbox: str | None = None, scale: float = 1.0):
    data = svc().frame(sha)
    if not data:
        raise ServiceError(404, "NO_FRAME", "frame expired or unknown")
    if bbox:
        try:
            box = [float(x) for x in bbox.split(",")]
        except ValueError:
            box = []
        if len(box) != 4 or not all(math.isfinite(v) for v in box):
            raise ServiceError(400, "BAD_BBOX", "bbox is four numbers: x,y,w,h")
        data, _ = gate.crop(data, box, scale=max(1.0, min(scale, 6.0)))
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400, immutable"})


# --- PayPal webhooks + public verification --------------------------------------------------------
@app.post("/api/webhooks/paypal")
async def webhook(req: Request):
    try:
        event = await req.json()
    except ValueError as e:
        raise ServiceError(400, "BAD_JSON", "webhook body is not JSON") from e
    if not isinstance(event, dict):
        raise ServiceError(400, "BAD_JSON", "webhook body is not a JSON object")
    # verification and storage are blocking HTTP calls: off the event loop
    return await run_in_threadpool(record_webhook, dict(req.headers), event)


PAYPAL_SIGNATURE_HEADERS = ("paypal-transmission-id", "paypal-transmission-time", "paypal-transmission-sig",
                            "paypal-cert-url", "paypal-auth-algo")


def obj(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def record_webhook(headers: dict, event: dict) -> dict:
    s = svc()
    verified = None
    if s.s.paypal_webhook_id:
        h = {k.lower(): v for k, v in headers.items()}
        if all(h.get(k) for k in PAYPAL_SIGNATURE_HEADERS):
            v = s.pp.verify_webhook(headers, event, s.s.paypal_webhook_id)
            verified = v.ok and v.body.get("verification_status") == "SUCCESS"
        else:  # no PayPal signature at all: refused here, without an outbound verify call or a ledger row
            verified = False
    res = obj(event.get("resource"))  # anyone can post here: every nested field is narrowed before .get
    related = obj(obj(res.get("supplementary_data")).get("related_ids"))
    row = {"id": event.get("id"), "event_type": event.get("event_type"), "resource_id": res.get("id"),
           "status": res.get("status"), "verified": verified, "received_at": iso(),
           "custom_id": res.get("custom_id") or related.get("order_id")}
    s.db.rpush_json("webhooks", row)
    s.db.ltrim("webhooks", -300, -1)
    return {"ok": True, "verified": verified}


@app.get("/api/integrations/verify")
def verify(rental: str | None = None, readback: bool = True):
    s = svc()
    out: dict[str, Any] = {"calls": s.calls(rental, 150), "webhooks": s.db.lrange_json("webhooks", -60, -1)}
    if rental:
        r = s.get(rental)
        out["rental"] = {k: r.get(k) for k in ("id", "state", "authorization_id", "settlement", "authorizations")}
        if readback and r.get("authorization_id"):
            # re-ask PayPal (not our ledger); cached 10 s per rental state so a polling page cannot flood PayPal,
            # and a release or capture is never answered with the status from before it
            key = f"readback:{r['authorization_id']}:{r.get('state')}"
            cache = s.db.get_json(key)
            if not cache:
                rb = s.pp.get_authorization(r["authorization_id"], quiet=True)
                cache = {"authorization_id": r["authorization_id"], "status": rb.body.get("status"),
                         "http_status": rb.status, "debug_id": rb.debug_id, "at": iso()}
                s.db.set_json(key, cache, ex=10)
            out["read_back"] = cache
    return out


@app.get("/api/close")
def close(date: str | None = None):
    return svc().daily_close(date)


# --- judge path -------------------------------------------------------------------------------------
@app.get("/api/judge/info")
def judge_info():
    s = svc()
    man = s.staged_manifest()
    return {"pool": len(s.s.judge_vault_ids), "staged_set": bool(man), "scripted_claims": (man or {}).get("scripted_claims"),
            "full_path": {"buyer_email": s.s.judge_buyer_email or None, "buyer_password": s.s.judge_buyer_password or None},
            "benchmarked_model": s.s.benchmarked_model or None}


@app.post("/api/judge")
def judge(req: Request):
    r = svc().mint_judge(client_ip(req))
    return {**svc().view(r, "shop"), "shop_key": r["keys"]["shop"], "renter_key": r["keys"]["renter"]}


@app.post("/api/judge/full")
def judge_full(req: Request):
    s = svc()
    s.rate_limit_judge(client_ip(req))  # the same budget as /api/judge: each one opens a real PayPal order
    r = s.create_rental("shop-demo", "veh-01", 1, kind="judge_full")
    out = s.approve(r["id"])
    s.db.zadd("judge:open", time.time(), r["id"])
    return {"id": r["id"], **out, "shop_key": r["keys"]["shop"], "renter_key": r["keys"]["renter"]}


@app.get("/api/health/judge")
def health_judge(req: Request):
    """One logged-out judge run end to end; non-200 on failure (hit daily 12-01 → 12-15)."""
    s = svc()
    try:
        r = s.mint_judge(f"health-{client_ip(req)}")
        k = r["keys"]
        man = s.staged_manifest()
        if man and man.get("scripted_claims") and s.s.benchmarked_model:
            for c in man["scripted_claims"]:
                s.claim(r["id"], k["shop"], c["angle"], c["bbox"], c["part"], c["damage_class"])
            s.propose(r["id"], k["shop"])
            for f in s.get(r["id"])["findings"]:
                if f["disposition"] == "chargeable":
                    s.decide_line(r["id"], k["renter"], f["id"], "accepted")
            r = s.settle(r["id"], k["renter"])
        else:
            r = s.release(r["id"], k["shop"])
        rb = s.pp.get_authorization(r["authorization_id"])
        ok = rb.body.get("status") in ("CAPTURED", "VOIDED")
        return JSONResponse({"ok": ok, "rental": r["id"], "read_back": rb.body.get("status"), "debug_id": rb.debug_id,
                             "path": "claims" if r.get("findings") else "release", "at": iso()},
                            status_code=200 if ok else 500)
    except ServiceError as e:
        return JSONResponse({"ok": False, "error": e.code, "message": e.message}, status_code=500)


# --- jobs -------------------------------------------------------------------------------------------
@app.get("/api/cron/daily")
def cron(authorization: str | None = Header(default=None)):
    s = svc()
    if not s.s.cron_secret or not same_secret(authorization or "", f"Bearer {s.s.cron_secret}"):
        raise ServiceError(401, "UNAUTHORIZED", "cron only")
    return s.cron_daily()


@app.post("/api/admin/reauthorize/{rid}")
def admin_reauth(rid: str, authorization: str | None = Header(default=None)):
    s = svc()
    if not s.s.cron_secret or not same_secret(authorization or "", f"Bearer {s.s.cron_secret}"):
        raise ServiceError(401, "UNAUTHORIZED", "admin only")
    r = s.reauthorize(rid)
    return {k: r.get(k) for k in ("id", "authorization_id", "reauthorized_at", "reauth_method", "reauth_refusal",
                                  "reauth_error", "authorizations")}

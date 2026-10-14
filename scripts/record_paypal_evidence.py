"""Record three real PayPal sandbox settlements, call by call, into evidence/paypal-sandbox-run.json.

    .venv/bin/python scripts/record_paypal_evidence.py

Each rental is a merchant-initiated AUTHORIZE (fee + deposit) on the judge pool's saved sandbox wallet,
with the fee captured from the hold (final_capture=false), exactly as /judge mints them:
  accepted   the shop taps a new mirror crack (priced from the tariff) and a side-panel dent the pickup
             photos already show; the renter accepts the crack -> ONE capture with final_capture=true ->
             read-back CAPTURED; then a second capture, which PayPal must refuse (422).
  clean      no new damage -> one tap releases the hold -> void -> read-back VOIDED.
  contested  the same two taps, but the renter contests the crack -> itemized invoice at the tariff price,
             sent and QR-coded; the whole hold voided.
The claim answers are SCRIPTED (tests/fakes.ScriptedVision) because the vision benchmark on the staged
photo set has not run yet. Every PayPal call, id and status in the file is real and read back from PayPal.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jaminan.config import Settings, load_local_env  # noqa: E402
from jaminan.paypal import PayPal, Resp, first_authorization  # noqa: E402
from jaminan.service import Service  # noqa: E402
from jaminan.store import MemoryStore  # noqa: E402
from tests.fakes import ScriptedVision, frame_bytes  # noqa: E402

MODEL = "scripted-test-model"
OUT = ROOT / "evidence" / "paypal-sandbox-run.json"
STEP_KEYS = ("at", "action", "method", "path", "http_status", "status", "amount", "final_capture", "authorization",
             "object_id", "issue", "debug_id", "ms", "request_id")


class RecordingPayPal(PayPal):
    """The product's client, plus what PayPal answered on each call: object status, amount, final_capture."""

    def call(self, method: str, path: str, action: str, body: dict | None = None, **kw) -> Resp:  # type: ignore[override]
        rows: list[dict] = []
        ledger, self.on_call = self.on_call, rows.append
        try:
            resp = super().call(method, path, action, body, **kw)
        finally:
            self.on_call = ledger
        sent = body or {}
        unit = (sent.get("purchase_units") or [{}])[0]
        auth = first_authorization(resp.body) if action.startswith("order.create") else None
        for row in rows:
            row.update(status=resp.body.get("status"), final_capture=sent.get("final_capture"),
                       amount=(sent.get("amount") or unit.get("amount") or {}).get("value"),
                       authorization={"id": auth["id"], "status": auth["status"]} if auth else None)
            if ledger:
                ledger(row)
        return resp


def service() -> Service:
    load_local_env()
    if not os.environ.get("PAYPAL_CLIENT_ID"):
        sys.exit("no PayPal sandbox credentials (env or ~/.config/paypal/sandbox.env)")
    vault = os.environ.get("JUDGE_VAULT_IDS", "3ug34380pw497712d").split(",")[0]
    os.environ.update({"JAMINAN_BENCHMARKED_MODEL": MODEL, "JUDGE_VAULT_IDS": vault})
    os.environ.setdefault("APP_URL", "https://jaminan.edycu.dev")
    s = Settings()
    vision = ScriptedVision(model=MODEL, claims={(3, "side_panel", "dent"): {"visible_at_pickup": True}})
    return Service(s, MemoryStore(prefix=f"jaminan:evidence:{uuid.uuid4().hex[:6]}:"),
                   RecordingPayPal(s.paypal_base, s.paypal_client_id, s.paypal_client_secret), vision)


def returned(svc: Service) -> tuple[str, dict]:
    """A fresh judge rental brought to RETURNED with synthetic frames (the staged photo set is not in yet)."""
    r = svc.mint_judge(f"evidence-{uuid.uuid4().hex[:6]}")
    rid, keys = r["id"], r["keys"]
    rr = svc.get(rid)
    for a in range(1, 9):
        svc.db.set_bytes(f"frame:p{a}", frame_bytes(a))
        svc.db.set_bytes(f"frame:r{a}", frame_bytes(100 + a))
    rr["photos"]["pickup"] = {str(a): {"sha256": f"p{a}", "angle": a, "low_tiles": []} for a in range(1, 9)}
    rr["photos"]["return"] = {str(a): {"sha256": f"r{a}", "angle": a, "low_tiles": []} for a in range(1, 9)}
    rr["state"] = "RETURNED"
    svc.db.set_json(f"rental:{rid}", rr)
    return rid, keys


def lines(r: dict) -> list[dict]:
    return [{"part": f["part"], "damage_class": f["damage_class"], "disposition": f["disposition"],
             "price_cents": f.get("price_cents"), "renter_decision": f.get("renter_decision"),
             "served_by": f.get("model")} for f in r["findings"]]


def record(svc: Service, name: str, rid: str, extra: dict | None = None) -> dict:
    r = svc.get(rid)
    st = r.get("settlement") or {}
    final = svc.pp.get_authorization(r["authorization_id"], rid)
    return {"name": name, "rental_id": rid, "order_id": r.get("order_id"),
            "authorization_id": r["authorization_id"], "authorized_cents": r["authorized_cents"],
            "fee_cents": r["fee_cents"], "deposit_cents": r["deposit_cents"],
            "fee_capture_id": r.get("fee_capture_id"), "tracking_number": r.get("tracking_number"),
            "lines": lines(r), "settlement": {k: st.get(k) for k in
                                              ("void", "capture_cents", "capture_id", "released_cents",
                                               "auth_read_back", "tap_to_readback_ms")},
            "final_read_back": final.body.get("status"),
            **(extra or {}),
            "steps": [{k: c.get(k) for k in STEP_KEYS} for c in svc.calls(rid)]}


def main() -> None:
    svc = service()
    svc.db.set_json("judge:seq", 9000)  # R-JUDGE-90xx: this recording's own series, apart from the live app's
    runs = []

    rid, k = returned(svc)
    new = svc.claim(rid, k["shop"], 2, [0.4, 0.3, 0.12, 0.12], "mirror_housing", "crack")["finding"]
    svc.claim(rid, k["shop"], 3, [0.45, 0.45, 0.1, 0.1], "side_panel", "dent")
    svc.propose(rid, k["shop"])
    svc.decide_line(rid, k["renter"], new["id"], "accepted")
    r = svc.settle(rid, k["renter"])
    again = svc.pp.capture(r["authorization_id"], 100, False, f"{rid}-again", "must be refused",
                           rental_id=rid, action="auth.capture.after_final")
    runs.append(record(svc, "accepted", rid, {"second_capture": {"http_status": again.status, "issue": again.issue,
                                                                  "debug_id": again.debug_id}}))

    rid, k = returned(svc)
    svc.release(rid, k["shop"])
    runs.append(record(svc, "clean", rid))

    rid, k = returned(svc)
    line = svc.claim(rid, k["shop"], 2, [0.4, 0.3, 0.12, 0.12], "mirror_housing", "crack")["finding"]
    svc.claim(rid, k["shop"], 3, [0.45, 0.45, 0.1, 0.1], "side_panel", "dent")
    svc.propose(rid, k["shop"])
    svc.decide_line(rid, k["renter"], line["id"], "contested")
    r = svc.settle(rid, k["renter"])
    inv = r.get("invoice") or {}
    runs.append(record(svc, "contested", rid, {"invoice": {k2: inv.get(k2) for k2 in
                                                           ("id", "create_status", "send_status", "qr_status")}
                                               | {"amount_cents": sum(i["amount_cents"] for i in inv.get("items", []))}}))

    doc = {"recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "environment": svc.s.paypal_base,
           "script": "scripts/record_paypal_evidence.py",
           "claim_answers": f"scripted ({MODEL}); the vision benchmark on the staged photo set is pending",
           "rental_ids": "R-JUDGE-90xx belong to this recording's in-memory store, not to the live app",
           "runs": runs}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    a, c, x = runs
    print(f"accepted  {a['rental_id']}  auth {a['authorization_id']}  capture {a['settlement']['capture_id']} "
          f"${a['settlement']['capture_cents'] / 100:.2f}  read-back {a['settlement']['auth_read_back']}  "
          f"2nd capture {a['second_capture']['http_status']} {a['second_capture']['issue']}")
    print(f"clean     {c['rental_id']}  auth {c['authorization_id']}  read-back {c['settlement']['auth_read_back']}")
    print(f"contested {x['rental_id']}  auth {x['authorization_id']}  invoice {x['invoice']['id']} "
          f"sent {x['invoice']['send_status']}  read-back {x['settlement']['auth_read_back']}")
    print(f"-> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

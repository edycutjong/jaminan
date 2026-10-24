"""Rental service: the one flow, from a single PayPal approval to one settlement.

Every PayPal call here is a transition of the rental state machine (rules.TRANSITIONS); every amount
comes from rules.py; the model only answers questions (vision.py). Records are JSON documents in
Upstash Redis under `jaminan:` (store.py), frames are JPEG ≤ 150 KB with a TTL.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import gate, rules, tariff
from .paypal import PayPal, PayPalError, approve_link, first_authorization, first_capture, payer_email, vault_of
from .store import Store

ANGLES = range(1, 9)
FRAME_EXPIRY = datetime(2026, 12, 31, tzinfo=timezone.utc)
JUDGE_VOID_AFTER_S = 2 * 3600
# Longer than the function's maxDuration (vercel.json: 120 s): a held lock can only expire after its holder is gone,
# never mid-capture (one PayPal write may take 3 × 30 s with retries).
LOCK_TTL_S = 130
# A void refused with these issues has nothing left to release.
VOID_DONE = ("AUTHORIZATION_ALREADY_VOIDED", "AUTHORIZATION_ALREADY_CAPTURED")
STAGED = Path(__file__).resolve().parents[1] / "fixtures" / "staged"


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(t: datetime | None = None) -> str:
    return (t or now()).isoformat(timespec="seconds")


def age_s(ts: str | None) -> float:
    return (now() - datetime.fromisoformat(ts)).total_seconds() if ts else 0.0


class Service:
    def __init__(self, settings, store: Store, paypal: PayPal, vision):
        self.s, self.db, self.vision = settings, store, vision
        self.pp = paypal
        self.pp.on_call = self._ledger

    # ------------------------------------------------------------------------------------------
    # ledger + persistence helpers
    # ------------------------------------------------------------------------------------------
    def _ledger(self, row: dict) -> None:
        if row.get("rental_id"):
            self.db.rpush_json(f"rental:{row['rental_id']}:calls", row)
        self.db.rpush_json("calls", row)
        self.db.ltrim("calls", -500, -1)

    def calls(self, rid: str | None = None, limit: int = 120) -> list[dict]:
        return self.db.lrange_json(f"rental:{rid}:calls" if rid else "calls", -limit, -1)

    def get(self, rid: str) -> dict:
        r = self.db.get_json(f"rental:{rid}")
        if not r:
            raise ServiceError(404, "RENTAL_NOT_FOUND", f"no rental {rid}")
        return r

    def _save(self, r: dict) -> dict:
        r["updated_at"] = iso()
        self.db.set_json(f"rental:{r['id']}", r)
        return r

    def _to(self, r: dict, state: str, **fields: Any) -> dict:
        rules.check_transition(r["state"], state)
        r.update(fields)
        r["state"] = state
        r.setdefault("history", []).append({"state": state, "at": iso()})
        return r

    @contextmanager
    def lock(self, rid: str, wait_s: float = 12.0):
        key, token = f"lock:{rid}", secrets.token_hex(12)
        deadline = time.time() + wait_s
        while not self.db.set_json(key, token, ex=LOCK_TTL_S, nx=True):
            if time.time() > deadline:
                raise ServiceError(409, "BUSY", "another request is changing this rental; retry")
            time.sleep(0.15)
        try:
            yield
        finally:
            self.db.delete_if(key, token)  # never release a lock another request now holds

    def auth(self, r: dict, key: str | None, role: str) -> None:
        """Capability keys: the renter's key travels in the QR link, the shop's stays on the shop phone."""
        want = r["keys"].get(role)
        if not key or not secrets.compare_digest(key, want):
            raise ServiceError(403, "FORBIDDEN", f"this action needs the {role}'s key for {r['id']}")

    def role_of(self, r: dict, key: str | None) -> str | None:
        for role in ("shop", "renter"):
            if key and secrets.compare_digest(key, r["keys"][role]):
                return role
        return None

    def view(self, r: dict, role: str | None) -> dict:
        """What a client may see: never the other party's key."""
        out = {k: v for k, v in r.items() if k != "keys"}
        if role:
            out["role"] = role
        if role == "shop":
            out["renter_link"] = f"{self.s.app_url}/r/{r['id']}?k={r['keys']['renter']}"
        out["tariff"] = tariff.load(r["tariff_version_id"]).public()
        out["chargeable_classes"] = list(self.s.chargeable_classes)
        out["benchmarked_model"] = self.s.benchmarked_model or None
        out["answers"] = {f["id"]: rules.Decision(f["disposition"], f.get("price_cents"), "").text(f["damage_class"])
                          for f in r.get("findings", [])}
        return out

    # ------------------------------------------------------------------------------------------
    # 1. counter → rental → one PayPal approval
    # ------------------------------------------------------------------------------------------
    def create_rental(self, shop_id: str, vehicle_id: str, days: int, kind: str = "standard",
                      rid: str | None = None) -> dict:
        shop, veh = tariff.shops().get(shop_id), tariff.vehicles().get(vehicle_id)
        if not shop or not veh or veh["shop_id"] != shop_id:
            raise ServiceError(404, "UNKNOWN_VEHICLE", "unknown shop or vehicle")
        if not 1 <= int(days) <= 28:
            raise ServiceError(422, "BAD_DAYS", "a rental is 1–28 days (a PayPal hold lives 29 days)")
        tv = tariff.load("tv1")
        rid = rid or f"R-{now().strftime('%m%d')}-{secrets.token_hex(4).upper()}"
        fee = veh["daily_fee_cents"] * int(days)
        r = {"id": rid, "kind": kind, "shop_id": shop_id, "vehicle_id": vehicle_id, "plate": veh["plate"],
             "vehicle_label": veh["label"], "days": int(days), "fee_cents": fee, "deposit_cents": veh["deposit_cents"],
             "authorized_cents": fee + veh["deposit_cents"], "tariff_version_id": tv.id, "tariff_sha256": tv.sha256,
             "state": "DRAFT", "created_at": iso(), "history": [{"state": "DRAFT", "at": iso()}],
             "keys": {"shop": secrets.token_urlsafe(18), "renter": secrets.token_urlsafe(18)},
             "photos": {"pickup": {}, "return": {}}, "closeups": [], "baseline_marks": [], "retake_requests": [],
             "confirmations": {}, "suggestions": [], "findings": [], "authorizations": [], "fines": [],
             "invoice": None, "settlement": None,
             # rental ids can repeat across re-seeds (R-JUDGE-<n>); the nonce keeps PayPal request ids and
             # invoice numbers unique so an old idempotent response is never replayed into a new rental
             "nonce": secrets.token_hex(4),
             "evidence_token": secrets.token_urlsafe(9)}
        self.db.set_json(f"rental:{rid}", r)
        self.db.zadd(f"shop:{shop_id}:rentals", time.time(), rid)
        return r

    def approve(self, rid: str) -> dict:
        with self.lock(rid):
            r = self.get(rid)
            if r["state"] != "DRAFT":
                raise ServiceError(409, "ALREADY_APPROVED", f"rental is {r['state']}")
            back = f"{self.s.app_url}/r/{rid}/approved?k={r['keys']['renter']}"
            res = self.pp.create_authorize_order(rid, r["authorized_cents"],
                                                 f"Scooter rental {rid}: fee + refundable damage deposit hold",
                                                 return_url=back, cancel_url=f"{self.s.app_url}/r/{rid}?k={r['keys']['renter']}",
                                                 nonce=r["nonce"])
            if not res.ok:
                raise ServiceError(502, "PAYPAL_ORDER_FAILED", str(PayPalError(res)), debug_id=res.debug_id)
            r["order_id"], r["approve_url"] = res.body["id"], approve_link(res.body)
            self._save(r)
            return {"order_id": r["order_id"], "approve_url": r["approve_url"]}

    def authorize(self, rid: str) -> dict:
        """After the renter approved on PayPal: authorize the order → the hold, plus the saved wallet."""
        with self.lock(rid):
            r = self.get(rid)
            if r["state"] != "DRAFT":
                return r  # idempotent: return-page reloads land here
            o = self.pp.get_order(r["order_id"], rid)
            if o.body.get("status") != "APPROVED":
                raise ServiceError(409, "NOT_APPROVED", f"PayPal order is {o.body.get('status')}, not APPROVED")
            res = self.pp.authorize_order(r["order_id"], rid)
            auth = first_authorization(res.body) if res.ok else None
            if not auth:
                raise ServiceError(502, "PAYPAL_AUTHORIZE_FAILED", str(PayPalError(res)), debug_id=res.debug_id)
            v = vault_of(res.body)
            self._record_auth(r, auth, replaces=None)
            self._to(r, "APPROVED", authorization_id=auth["id"], auth_created_at=iso(),
                     auth_expires_at=auth.get("expiration_time"), vault_id=v.get("id"),
                     vault_status=v.get("status"), customer_id=(v.get("customer") or {}).get("id"),
                     payer_email=payer_email(res.body),
                     # PayPal returns the SAME vault token for the same buyer + merchant, so a judge's full-path
                     # approval with the shared sandbox buyer yields a pool token: never delete one of those
                     vault_revocable=v.get("id") not in self.s.judge_vault_ids)
            return self._save(r)

    def _record_auth(self, r: dict, auth: dict, replaces: str | None) -> None:
        r.setdefault("authorizations", []).append({"id": auth["id"], "status": auth.get("status"), "created_at": iso(),
                                                   "expires_at": auth.get("expiration_time"), "replaces": replaces})

    # ------------------------------------------------------------------------------------------
    # 2. pickup walkaround → shared baseline → fee capture + tracking
    # ------------------------------------------------------------------------------------------
    def _frame_ttl(self) -> int:
        return max(3600, int((FRAME_EXPIRY - now()).total_seconds()))

    def frame(self, sha: str) -> bytes | None:
        data = self.db.get_bytes(f"frame:{sha}")
        if data is None and (STAGED / "frames" / f"{sha}.jpg").exists():
            data = (STAGED / "frames" / f"{sha}.jpg").read_bytes()
        return data

    def frame_required(self, sha: str) -> bytes:
        data = self.frame(sha)
        if data is None:
            raise ServiceError(410, "FRAME_EXPIRED", "a stored photo for this rental has expired; retake it")
        return data

    def add_photo(self, rid: str, key: str | None, phase: str, angle: int, data: bytes, closeup_angle: int | None = None) -> dict:
        r = self.get(rid)
        self.auth(r, key, "renter" if phase != "return" else self.role_of(r, key) or "shop")
        if phase in ("pickup", "pickup_closeup") and r["state"] != "APPROVED":
            raise ServiceError(409, "BASELINE_LOCKED", "pickup photos are taken before the baseline is confirmed")
        if phase == "return" and r["state"] != "OUT":
            raise ServiceError(409, "NOT_OUT", "return photos are taken while the scooter is out")
        if phase not in ("pickup", "pickup_closeup", "return"):
            raise ServiceError(422, "BAD_PHASE", "phase must be pickup, pickup_closeup or return")
        res, jpeg = gate.check(data)
        if phase != "pickup_closeup" and not res.ok:
            return {"accepted": False, "gate": res.public()}
        self.db.set_bytes(f"frame:{res.sha256}", jpeg, ex=self._frame_ttl())
        photo = {"sha256": res.sha256, "angle": int(angle), "phase": phase, "captured_at": iso(),
                 "blur_var": round(res.blur_var, 1), "glare_frac": round(res.glare_frac, 4), "low_tiles": res.low_tiles}
        with self.lock(rid):
            r = self.get(rid)
            if phase == "pickup_closeup":
                r["closeups"].append({**photo, "id": f"C{len(r['closeups']) + 1}", "located": None, "bbox": None})
            else:
                r["photos"][phase][str(angle)] = photo
                r["retake_requests"] = [x for x in r["retake_requests"] if x["angle"] != int(angle)] \
                    if phase == "pickup" else r["retake_requests"]
                if phase == "pickup":
                    r["confirmations"] = {}  # a changed baseline needs both confirmations again
            self._save(r)
        return {"accepted": True, "gate": res.public(), "photo": photo}

    def premark(self, rid: str, key: str | None) -> dict:
        """Model pre-marks visible existing damage per pickup angle and locates the renter's close-ups."""
        r = self.get(rid)
        self.auth(r, key, "renter")
        if r["state"] != "APPROVED":
            raise ServiceError(409, "BASELINE_LOCKED", "pre-marking happens before the baseline is confirmed")
        missing = [a for a in ANGLES if str(a) not in r["photos"]["pickup"]]
        if missing:
            raise ServiceError(409, "ANGLES_MISSING", f"pickup angles missing: {missing}")

        def mark_angle(a: int):
            return a, self.vision.premark(self.frame_required(r["photos"]["pickup"][str(a)]["sha256"]), a)

        def locate(c: dict):
            angle = c["angle"]
            return c["id"], self.vision.locate_closeup(self.frame_required(r["photos"]["pickup"][str(angle)]["sha256"]),
                                                       self.frame_required(c["sha256"]), angle)

        with ThreadPoolExecutor(max_workers=8) as ex:
            marks = list(ex.map(mark_angle, ANGLES))
            located = list(ex.map(locate, r["closeups"]))
        with self.lock(rid):
            r = self.get(rid)
            keep = [m for m in r["baseline_marks"] if m["source"] != "model"]
            calls = []
            for a, call in marks:
                calls.append({"angle": a, **call.meta()})
                for i, m in enumerate(call.parsed.marks if call.ok else []):
                    keep.append({"id": f"M{a}-{i + 1}", "angle": a, "part": m.part, "damage_class": m.damage_class,
                                 "bbox": m.bbox, "source": "model", "model": call.model, "confirmed": False,
                                 "removed": False})
            for cid, call in located:
                c = next(x for x in r["closeups"] if x["id"] == cid)
                c["located"] = bool(call.ok and call.parsed.located and call.parsed.bbox)
                c["bbox"] = call.parsed.bbox if c["located"] else None
                c["locate_model"] = call.model
            r["baseline_marks"], r["premark_calls"], r["confirmations"] = keep, calls, {}
            self._save(r)
            return r

    def edit_mark(self, rid: str, key: str | None, action: str, mark: dict) -> dict:
        """Only the renter can remove a model pre-mark; the shop can only add marks; the renter can add too."""
        with self.lock(rid):
            r = self.get(rid)
            role = self.role_of(r, key)
            if not role:
                raise ServiceError(403, "FORBIDDEN", "needs the renter's or the shop's key")
            if r["state"] != "APPROVED":
                raise ServiceError(409, "BASELINE_LOCKED", "the baseline is already confirmed")
            if action == "add":
                if mark.get("damage_class") not in tariff.DAMAGE_CLASSES or int(mark.get("angle", 0)) not in ANGLES:
                    raise ServiceError(422, "BAD_MARK", "a mark needs angle 1–8 and a damage class")
                r["baseline_marks"].append({"id": f"{role[0].upper()}{len(r['baseline_marks']) + 1}",
                                            "angle": int(mark["angle"]), "part": mark.get("part", "other"),
                                            "damage_class": mark["damage_class"], "bbox": mark.get("bbox"),
                                            "source": role, "confirmed": False, "removed": False})
            elif action == "remove":
                m = next((x for x in r["baseline_marks"] if x["id"] == mark.get("id")), None)
                if not m:
                    raise ServiceError(404, "NO_MARK", "no such mark")
                if role != "renter" or m["source"] != "model":
                    raise ServiceError(403, "ONLY_RENTER_REMOVES_MODEL_MARKS",
                                       "only the renter can remove a model pre-mark; the shop can only add marks")
                m["removed"] = True
            else:
                raise ServiceError(422, "BAD_ACTION", "action must be add or remove")
            r["confirmations"] = {}
            return self._save(r)

    def request_retake(self, rid: str, key: str | None, angle: int, reason: str = "low comparability") -> dict:
        with self.lock(rid):
            r = self.get(rid)
            self.auth(r, key, "shop")
            if r["state"] != "APPROVED":
                raise ServiceError(409, "BASELINE_LOCKED", "the baseline is already confirmed")
            r["retake_requests"].append({"angle": int(angle), "reason": reason, "at": iso()})
            r["confirmations"] = {}
            return self._save(r)

    def baseline_hash(self, r: dict) -> str:
        doc = {"photos": {a: p["sha256"] for a, p in sorted(r["photos"]["pickup"].items())},
               "closeups": [c["sha256"] for c in r["closeups"]],
               "marks": sorted([(m["angle"], m["part"], m["damage_class"], m["source"]) for m in r["baseline_marks"]
                                if not m.get("removed")]),
               "tariff": r["tariff_sha256"]}
        return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()

    def confirm_baseline(self, rid: str, key: str | None) -> dict:
        """Both parties confirm → capture the fee from the hold (final_capture=false) → tracking = handover record."""
        with self.lock(rid):
            r = self.get(rid)
            role = self.role_of(r, key)
            if not role:
                raise ServiceError(403, "FORBIDDEN", "needs the renter's or the shop's key")
            if r["state"] != "APPROVED":
                raise ServiceError(409, "BASELINE_LOCKED", f"rental is {r['state']}")
            missing = [a for a in ANGLES if str(a) not in r["photos"]["pickup"]]
            if missing:
                raise ServiceError(409, "ANGLES_MISSING", f"no baseline without all 8 angles; missing {missing}")
            if r["retake_requests"]:
                raise ServiceError(409, "RETAKE_PENDING", "the shop asked for a retake")
            r["confirmations"][role] = {"at": iso(), "baseline_sha256": self.baseline_hash(r)}
            if not {"renter", "shop"} <= set(r["confirmations"]):
                return self._save(r)
            if len({c["baseline_sha256"] for c in r["confirmations"].values()}) != 1:
                r["confirmations"] = {role: r["confirmations"][role]}
                return self._save(r)
            return self._handover(r)

    def _handover(self, r: dict) -> dict:
        rid = r["id"]
        sha = self.baseline_hash(r)
        for m in r["baseline_marks"]:
            m["confirmed"] = not m.get("removed")
        cap = self.pp.capture(r["authorization_id"], r["fee_cents"], False, f"{rid}-{r['nonce']}-fee",
                              f"Rental fee {rid}. Damage deposit stays on hold.", rental_id=rid, action="auth.capture.fee")
        if not cap.ok:
            raise ServiceError(502, "PAYPAL_CAPTURE_FAILED", str(PayPalError(cap)), debug_id=cap.debug_id)
        self._to(r, "HELD", fee_capture_id=cap.body["id"], fee_captured_cents=r["fee_cents"], baseline_sha256=sha)
        tracking = f"JMN-{rid}-{sha[:8]}"
        tr = self.pp.add_tracking(r["order_id"], cap.body["id"], tracking, rental_id=rid) if r.get("order_id") else None
        rb = self.pp.get_authorization(r["authorization_id"], rid)
        self._to(r, "OUT", tracking_number=tracking, tracking_ok=bool(tr and tr.ok), picked_up_at=iso(),
                 auth_status=rb.body.get("status"))
        return self._save(r)

    # ------------------------------------------------------------------------------------------
    # 3. return walkaround → suggested taps → pointed claims (the ONE pricing path)
    # ------------------------------------------------------------------------------------------
    def complete_return(self, rid: str, key: str | None) -> dict:
        with self.lock(rid):
            r = self.get(rid)
            if not self.role_of(r, key):
                raise ServiceError(403, "FORBIDDEN", "needs the renter's or the shop's key")
            missing = [a for a in ANGLES if str(a) not in r["photos"]["return"]]
            if missing:
                raise ServiceError(409, "ANGLES_MISSING", f"return angles missing: {missing}")
            self._to(r, "RETURNED", returned_at=iso())
            return self._save(r)

    def suggest(self, rid: str, key: str | None) -> dict:
        r = self.get(rid)
        self.auth(r, key, "shop")
        if r["state"] not in ("RETURNED", "CLAIMED"):
            raise ServiceError(409, "NOT_RETURNED", f"rental is {r['state']}")
        marks = [m for m in r["baseline_marks"] if m.get("confirmed")]

        def one(a: int):
            return a, self.vision.suggest(self.frame_required(r["photos"]["pickup"][str(a)]["sha256"]),
                                          self.frame_required(r["photos"]["return"][str(a)]["sha256"]), a,
                                          [m for m in marks if m["angle"] == a])

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(one, ANGLES))
        with self.lock(rid):
            r = self.get(rid)
            taps = [f for f in r["findings"]]
            out = []
            for a, call in results:
                for i, m in enumerate(call.parsed.marks if call.ok else []):
                    merged = next((f for f in taps if f["angle"] == a and
                                   rules.bbox_overlap(m.bbox, f["bbox_return"]) > 0.3), None)
                    out.append({"id": f"S{a}-{i + 1}", "angle": a, "part": m.part, "damage_class": m.damage_class,
                                "bbox_return": m.bbox, "confidence": m.confidence, "model": call.model,
                                "request_id": call.request_id,
                                "status": "merged" if merged else "shown", "merged_into": merged["id"] if merged else None})
            r["suggestions"] = out
            r["suggest_run"] = {"at": iso(), "ms": int((time.perf_counter() - t0) * 1000),
                                "calls": [{"angle": a, **c.meta()} for a, c in results]}
            return self._save(r)

    def dismiss_suggestion(self, rid: str, key: str | None, sid: str) -> dict:
        with self.lock(rid):
            r = self.get(rid)
            self.auth(r, key, "shop")
            s = next((x for x in r["suggestions"] if x["id"] == sid), None)
            if not s:
                raise ServiceError(404, "NO_SUGGESTION", sid)
            s["status"] = "dismissed"
            return self._save(r)

    def claim(self, rid: str, key: str | None, angle: int, bbox: list[float], part: str, damage_class: str,
              suggestion_id: str | None = None) -> dict:
        r = self.get(rid)
        self.auth(r, key, "shop")
        if r["state"] not in ("RETURNED", "CLAIMED"):
            raise ServiceError(409, "NOT_RETURNED", f"claims are made on a returned rental; it is {r['state']}")
        tv = tariff.load(r["tariff_version_id"])
        price = tv.price(part, damage_class)
        if price is None:
            raise ServiceError(422, "NOT_IN_TARIFF", "part + class must come from the published tariff list")
        angle = int(angle)
        if angle not in ANGLES or len(bbox) != 4:
            raise ServiceError(422, "BAD_TAP", "a tap needs angle 1–8 and a box [x, y, w, h]")
        bbox = [min(max(float(v), 0.0), 1.0) for v in bbox]
        self._no_duplicate(r, angle, bbox, part, damage_class)
        pick, ret = r["photos"]["pickup"][str(angle)], r["photos"]["return"][str(angle)]
        ret_jpg, pick_jpg = self.frame_required(ret["sha256"]), self.frame_required(pick["sha256"])
        ret_crop, ret_region = gate.crop(ret_jpg, bbox, scale=2.0)
        pick_area, pick_region = gate.crop(pick_jpg, bbox, scale=4.0)
        closeups = [c for c in r["closeups"] if c["angle"] == angle and c.get("located") and c.get("bbox")
                    and rules.bbox_overlap(c["bbox"], pick_region) > 0]
        call = self.vision.claim(ret_crop, pick_area, [self.frame_required(c["sha256"]) for c in closeups[:1]], part,
                                 damage_class, angle)
        ans = call.parsed.model_dump() if call.ok else None
        d = rules.decide_claim(answer=ans, serving_model=call.model, benchmarked_model=self.s.benchmarked_model,
                               part=part, damage_class=damage_class, angle=angle, tap_bbox=bbox, price_cents=price,
                               baseline_marks=r["baseline_marks"], pickup_low_tiles=pick.get("low_tiles", []),
                               chargeable_classes=self.s.chargeable_classes, confidence_floor=self.s.confidence_floor)
        pickup_bbox = gate.map_back(ans["pickup_bbox"], pick_region) if ans and ans.get("pickup_bbox") else None
        with self.lock(rid):
            r = self.get(rid)
            if r["state"] not in ("RETURNED", "CLAIMED"):
                raise ServiceError(409, "NOT_RETURNED", f"rental is {r['state']}")
            self._no_duplicate(r, angle, bbox, part, damage_class)  # again under the lock: two fast taps
            f = {"id": f"L{len(r['findings']) + 1}", "angle": angle, "part": part, "damage_class": damage_class,
                 "source": "confirmed_suggestion" if suggestion_id else "shop_claim", "suggestion_id": suggestion_id,
                 "bbox_return": bbox, "bbox_pickup": pickup_bbox, "pickup_region": pick_region,
                 "return_region": ret_region, "pickup_sha256": pick["sha256"], "return_sha256": ret["sha256"],
                 "closeup_ids": [c["id"] for c in closeups[:1]], **{k: (ans or {}).get(k) for k in rules.CLAIM_FIELDS},
                 "confidence": (ans or {}).get("confidence"), "rationale": (ans or {}).get("rationale"),
                 "model": call.model, "model_request_id": call.request_id, "model_ms": call.ms,
                 "model_error": call.error, "disposition": d.disposition, "reason": d.reason,
                 "price_cents": d.price_cents if d.disposition == "chargeable" else None,
                 "tariff_price_cents": price, "renter_decision": None, "at": iso()}
            r["findings"].append(f)
            if suggestion_id:
                for s in r["suggestions"]:
                    if s["id"] == suggestion_id:
                        s["status"] = "confirmed"
            if r["state"] == "RETURNED":
                self._to(r, "CLAIMED")
            self._save(r)
            return {"finding": f, "answer": d.text(damage_class), "answer_id": d.text(damage_class, "id")}

    @staticmethod
    def _no_duplicate(r: dict, angle: int, bbox: list[float], part: str, damage_class: str) -> None:
        for f in r["findings"]:
            if f["angle"] == angle and f["part"] == part and f["damage_class"] == damage_class and \
                    max(rules.bbox_overlap(bbox, f["bbox_return"]), rules.bbox_overlap(f["bbox_return"], bbox)) > 0.5:
                raise ServiceError(409, "DUPLICATE_CLAIM", f"{f['id']} already claims this spot as {part}/{damage_class}")

    def propose(self, rid: str, key: str | None) -> dict:
        """The shop sends its lines to the renter; nothing more can be added after this."""
        with self.lock(rid):
            r = self.get(rid)
            self.auth(r, key, "shop")
            self._to(r, "PROPOSED", proposed_at=iso())
            return self._save(r)

    # ------------------------------------------------------------------------------------------
    # 4. renter settles: accepted lines → one final capture; none → void; contested → invoice
    # ------------------------------------------------------------------------------------------
    def decide_line(self, rid: str, key: str | None, line_id: str, decision: str) -> dict:
        if decision not in ("accepted", "contested"):
            raise ServiceError(422, "BAD_DECISION", "accepted or contested")
        with self.lock(rid):
            r = self.get(rid)
            self.auth(r, key, "renter")
            if r["state"] != "PROPOSED":
                raise ServiceError(409, "NOT_PROPOSED", f"rental is {r['state']}")
            f = next((x for x in r["findings"] if x["id"] == line_id), None)
            if not f:
                raise ServiceError(404, "NO_LINE", line_id)
            if f["disposition"] != "chargeable":
                raise ServiceError(409, "NOT_CHARGEABLE", f"{line_id} is {f['disposition']}: nothing to accept")
            f["renter_decision"], f["decided_at"] = decision, iso()
            return self._save(r)

    def settle(self, rid: str, key: str | None, force: bool = False) -> dict:
        with self.lock(rid, wait_s=25):
            r = self.get(rid)
            if not force:
                self.auth(r, key, "renter")
            if r.get("settlement"):
                return r  # I4 at our level: a replayed settle is a no-op
            if r["state"] not in rules.OPEN_HOLD_STATES:
                raise ServiceError(409, "NOT_SETTLEABLE", f"rental is {r['state']}")
            if r["state"] != "PROPOSED" and not force:
                raise ServiceError(409, "NOT_PROPOSED", "the shop has not sent its lines to the renter yet")
            tv = tariff.load(r["tariff_version_id"])
            try:
                plan = rules.settle_plan(fee_cents=r["fee_cents"], deposit_cents=r["deposit_cents"],
                                         authorized_cents=r["authorized_cents"],
                                         fee_captured_cents=r.get("fee_captured_cents", 0), lines=r["findings"],
                                         tariff_price=tv.price, force=force)
            except rules.SettleBlocked as e:
                raise ServiceError(409, "SETTLE_BLOCKED", str(e)) from e
            aid = r["authorization_id"]
            t_tap = time.perf_counter()
            if plan.void:
                res = self.pp.void(aid, rid)
                if not res.ok and res.issue != "AUTHORIZATION_ALREADY_VOIDED":
                    raise ServiceError(502, "PAYPAL_VOID_FAILED", str(PayPalError(res)), debug_id=res.debug_id)
                capture_id = None
            else:
                names = ", ".join(f"{l['part'].replace('_', ' ')} {l['damage_class'].replace('_', ' ')}" for l in plan.accepted)
                res = self.pp.capture(aid, plan.capture_cents, True, f"{rid}-{r['nonce']}-settle",
                                      f"Accepted damage ({names}). The rest of the hold is released.", rental_id=rid,
                                      action="auth.capture.final")
                if not res.ok:
                    raise ServiceError(502, "PAYPAL_CAPTURE_FAILED", str(PayPalError(res)), debug_id=res.debug_id)
                capture_id = res.body.get("id")
            rb = self.pp.get_authorization(aid, rid)   # the stamp fires on PayPal's read-back, not ours
            read_back = rb.body.get("status")
            self._to(r, "RELEASED" if plan.void else "SETTLED")
            r["settlement"] = {"at": iso(), "void": plan.void, "capture_cents": plan.capture_cents,
                               "capture_id": capture_id, "released_cents": r["deposit_cents"] - plan.capture_cents,
                               "auth_read_back": read_back, "debug_id": res.debug_id,
                               "tap_to_readback_ms": int((time.perf_counter() - t_tap) * 1000),
                               "accepted": [l["id"] for l in plan.accepted], "contested": [l["id"] for l in plan.contested],
                               "forced": force}
            r["settle_capture_id"], r["auth_status"] = capture_id, read_back
            for a in r["authorizations"]:
                if a["id"] == aid:
                    a["status"] = read_back
            if plan.invoice_items:
                self._invoice(r, plan.invoice_items)
            self.db.zrem("judge:open", rid)
            return self._save(r)

    def _invoice(self, r: dict, items: list[dict]) -> None:
        rid = r["id"]
        number = f"JMN-{rid}-{r['nonce'][:4]}"[-25:]
        evidence = f"{self.s.app_url}/r/{rid}/evidence?t={r.get('evidence_token', '')}"
        res = self.pp.create_invoice(rid, number, r.get("payer_email"),
                                     [{"name": i["name"][:200], "quantity": "1",
                                       "unit_amount": {"currency_code": "USD", "value": f"{i['amount_cents'] / 100:.2f}"}}
                                      for i in items],
                                     note=f"Itemized at the shop's published tariff ({r['tariff_version_id']}, sha256 "
                                          f"{r['tariff_sha256'][:12]}). Evidence pack: {evidence}")
        inv: dict[str, Any] = {"items": items, "create_status": res.status, "debug_id": res.debug_id,
               "id": (res.body.get("id") or (res.body.get("href", "").rsplit("/", 1)[-1] if res.body.get("href") else None))}
        if res.ok and inv["id"]:
            sent = self.pp.send_invoice(inv["id"], rid)
            inv["send_status"] = sent.status
            inv["payer_link"] = next((l["href"] for l in sent.body.get("links", []) if l.get("rel") == "payer-view"), None) \
                if sent.ok else None
            qr = self.pp.invoice_qr(inv["id"], rid)
            inv["qr_status"] = qr.status
            if qr.ok:
                raw = qr.body.get("raw") or ""
                inv["qr_png_b64"] = raw if raw and not raw.startswith("{") else None
        r["invoice"] = inv
        if inv["id"] and r["state"] in ("SETTLED", "RELEASED"):
            self._to(r, "INVOICED")

    def release(self, rid: str, key: str | None) -> dict:
        """Clean return: one tap on the shop phone releases the hold (void)."""
        r = self.get(rid)
        self.auth(r, key, "shop")  # the renter cannot void the deposit while the scooter is out
        if any(f["disposition"] == "chargeable" for f in r["findings"]):
            raise ServiceError(409, "HAS_LINES", "there are priced lines: the renter settles them")
        return self.settle(rid, key, force=True)

    def revoke_vault(self, rid: str, key: str | None) -> dict:
        with self.lock(rid):
            r = self.get(rid)
            self.auth(r, key, "renter")
            if not r.get("vault_id"):
                raise ServiceError(409, "NO_VAULT", "no saved PayPal on this rental")
            req = {"method": "DELETE", "path": f"/v3/vault/payment-tokens/{r['vault_id']}"}
            if not r.get("vault_revocable"):
                r["vault_revoke"] = {"shown_only": True, "request": req, "at": iso(),
                                     "why": "judge pool token — deleting it would break /judge for the next visitor"}
                return self._save(r)
            res = self.pp.delete_payment_token(r["vault_id"], rid)
            r["vault_revoke"] = {"shown_only": False, "request": req, "status": res.status, "debug_id": res.debug_id,
                                 "at": iso()}
            if res.ok:
                r["vault_status"] = "DELETED"
            return self._save(r)

    def evidence(self, rid: str, key: str | None = None, token: str | None = None) -> dict:
        r = self.get(rid)
        ok_token = bool(token and r.get("evidence_token") and secrets.compare_digest(token, r["evidence_token"]))
        if not ok_token and not self.role_of(r, key):
            raise ServiceError(403, "FORBIDDEN", "the evidence pack needs the renter's or shop's key, or its link")
        return {"rental": r["id"], "tariff_version": r["tariff_version_id"], "tariff_sha256": r["tariff_sha256"],
                "baseline_sha256": r.get("baseline_sha256"), "tracking_number": r.get("tracking_number"),
                "pickup": r["photos"]["pickup"], "closeups": r["closeups"], "return": r["photos"]["return"],
                "baseline_marks": r["baseline_marks"], "confirmations": r["confirmations"],
                "findings": [{k: f.get(k) for k in ("id", "angle", "part", "damage_class", "source", "bbox_return",
                                                    "bbox_pickup", *rules.CLAIM_FIELDS, "confidence", "rationale",
                                                    "model", "model_request_id", "disposition", "reason", "price_cents",
                                                    "renter_decision", "pickup_sha256", "return_sha256", "at")}
                             for f in r["findings"]],
                "benchmarked_model": self.s.benchmarked_model or None,
                "settlement": r.get("settlement"), "authorizations": r.get("authorizations"),
                "paypal_calls": self.calls(rid, 200)}

    # ------------------------------------------------------------------------------------------
    # 5. long rentals, expiry guard, fines, daily close
    # ------------------------------------------------------------------------------------------
    def reauthorize(self, rid: str) -> dict:
        """Day 4–29, once: re-secure the remaining deposit. If PayPal refuses (S11 FAIL), the kill row:
        a merchant-initiated AUTHORIZE on the saved wallet, then void the old hold."""
        with self.lock(rid):
            r = self.get(rid)
            if r.get("reauthorized_at"):
                return r
            old = r["authorization_id"]
            res = self.pp.reauthorize(old, r["deposit_cents"], rid)
            if res.ok:
                self._record_auth(r, res.body, replaces=old)
                r.update(authorization_id=res.body["id"], reauthorized_at=iso(), reauth_method="reauthorize")
            elif r.get("vault_id"):
                mit = self.pp.create_vault_order(f"{rid}-resecure", r["vault_id"], r["deposit_cents"], "AUTHORIZE",
                                                 f"Deposit hold renewed for rental {rid} (past 3 days)", rental_id=rid,
                                                 nonce=r["nonce"])
                auth = first_authorization(mit.body) if mit.ok else None
                if not auth:
                    r["reauth_error"] = {"reauthorize": res.issue, "mit": mit.issue, "at": iso()}
                    return self._save(r)
                v = self.pp.void(old, rid)
                if not v.ok and v.issue not in VOID_DONE:
                    # the new hold stands; the old one is still open on PayPal, so the daily job retries the void
                    r["stale_hold"] = {"authorization_id": old, "issue": v.issue, "debug_id": v.debug_id, "at": iso()}
                self._record_auth(r, auth, replaces=old)
                r.update(authorization_id=auth["id"], reauthorized_at=iso(), reauth_method="mit_resecure",
                         reauth_refusal=res.issue, fee_captured_cents=0, authorized_cents=r["deposit_cents"])
            else:
                r["reauth_error"] = {"reauthorize": res.issue, "at": iso()}
            return self._save(r)

    def retry_stale_void(self, rid: str) -> str:
        """Void a replaced hold that PayPal refused to void during the re-secure (see reauthorize)."""
        with self.lock(rid):
            r = self.get(rid)
            stale = r.get("stale_hold")
            if not stale:
                return "none"
            v = self.pp.void(stale["authorization_id"], rid)
            if v.ok or v.issue in VOID_DONE:
                r.pop("stale_hold")
                self._save(r)
                return "voided"
            r["stale_hold"].update(issue=v.issue, debug_id=v.debug_id, retried_at=iso())
            self._save(r)
            return "open"

    def create_fine(self, rid: str, key: str | None, image: bytes, ticket_amount_idr: int) -> dict:
        r = self.get(rid)
        self.auth(r, key, "shop")
        if r["state"] not in ("SETTLED", "RELEASED", "INVOICED", "CLOSED"):
            raise ServiceError(409, "RENTAL_OPEN", "fines attach to a returned, settled rental")
        has_vault = bool(r.get("vault_id")) and r.get("vault_status") != "DELETED"
        tv = tariff.load(r["tariff_version_id"])
        res, jpeg = gate.check(image)
        self.db.set_bytes(f"frame:{res.sha256}", jpeg, ex=self._frame_ttl())
        call = self.vision.read_ticket(jpeg, list(tv.fine_ceilings))
        read = call.parsed.model_dump() if call.ok else {}
        q = rules.fine_quote(plate_read=read.get("plate"), rental_plate=r["plate"], ticket_time=read.get("time"),
                             pickup_at=r.get("picked_up_at") or r["created_at"], return_at=r.get("returned_at"),
                             violation_read=read.get("violation"), ceilings=tv.fine_ceilings,
                             ticket_amount_idr=ticket_amount_idr, idr_per_usd=tv.idr_per_usd,
                             admin_fee_cents=tv.admin_fee_cents)
        fid = f"F-{secrets.token_hex(3).upper()}"
        fine = {"id": fid, "rental_id": rid, "ticket_sha256": res.sha256, "read": read, "model": call.model,
                "model_request_id": call.request_id, "model_error": call.error,
                "ticket_amount_idr": int(ticket_amount_idr), "quote": q.__dict__, "status":
                "notified" if q.chargeable else "not_chargeable", "notified_at": iso(),
                "contest_until": iso(now() + timedelta(hours=72)), "capture_id": None, "invoice_id": None}
        if q.chargeable and not has_vault:
            # the renter removed saved PayPal: the fine arrives as an itemized invoice instead (consent copy)
            inv = self._fine_invoice(r, fine, "Traffic fine (e-TLE) during the rental")
            fine.update(status="invoiced", invoice_id=inv)
        self.db.set_json(f"fine:{fid}", fine)
        if q.chargeable and has_vault:
            self.db.zadd("fines:due", (now() + timedelta(hours=72)).timestamp(), fid)
        with self.lock(rid):
            r = self.get(rid)
            r["fines"].append(fid)
            self._save(r)
        return fine

    def contest_fine(self, rid: str, key: str | None, fid: str) -> dict:
        r = self.get(rid)
        self.auth(r, key, "renter")
        f = self.db.get_json(f"fine:{fid}")
        if not f or f["rental_id"] != rid:
            raise ServiceError(404, "NO_FINE", fid)
        if f["status"] != "notified" or iso() > f["contest_until"]:
            raise ServiceError(409, "NOT_CONTESTABLE", f"fine is {f['status']}")
        f["status"], f["contested_at"] = "contested_invoiced", iso()
        f["invoice_id"] = self._fine_invoice(r, f, "Traffic fine (e-TLE) during the rental, contested")
        self.db.zrem("fines:due", fid)
        self.db.set_json(f"fine:{fid}", f)
        return f

    def _fine_invoice(self, r: dict, f: dict, name: str) -> str | None:
        res = self.pp.create_invoice(r["id"], f"JMN-{f['id']}-{r['nonce'][:4]}", r.get("payer_email"),
                                     [{"name": name, "quantity": "1",
                                       "unit_amount": {"currency_code": "USD",
                                                       "value": f"{f['quote']['amount_cents'] / 100:.2f}"}}],
                                     note=f"Ticket image sha256 {f['ticket_sha256'][:12]}; amount capped at the "
                                          f"published ceiling of the article on the ticket.")
        inv = res.body.get("id") or (res.body.get("href", "").rsplit("/", 1)[-1] or None)
        if res.ok and inv:
            self.pp.send_invoice(inv, r["id"])
        return inv

    def capture_fine(self, fid: str) -> dict:
        f = self.db.get_json(f"fine:{fid}")
        if not f or f["status"] != "notified":
            return f or {}
        r = self.get(f["rental_id"])
        res = self.pp.create_vault_order(fid, r["vault_id"], f["quote"]["amount_cents"], "CAPTURE",
                                         f"e-TLE traffic fine during rental {r['id']} (ticket sha256 {f['ticket_sha256'][:12]})", rental_id=r["id"])
        cap = first_capture(res.body) if res.ok else None
        f["status"] = "captured" if cap else "capture_failed"
        f["capture_id"], f["captured_at"], f["debug_id"] = (cap or {}).get("id"), iso(), res.debug_id
        self.db.zrem("fines:due", fid)
        self.db.set_json(f"fine:{fid}", f)
        return f

    def shop_rentals(self, shop_id: str, limit: int = 60) -> list[dict]:
        ids = self.db.zrange(f"shop:{shop_id}:rentals", 0, limit - 1, rev=True)
        return [x for x in self.db.mget_json([f"rental:{i}" for i in ids]) if x]

    def daily_close(self, date: str | None = None, shop_id: str = "shop-demo") -> dict:
        """Ledger vs PayPal: captures matched in Transaction Search (it can lag — unmatched = pending);
        voids re-read per authorization, since Transaction Search may not list them."""
        day = date or now().date().isoformat()
        rentals = [r for r in self.shop_rentals(shop_id, 200) if (r.get("settlement") or {}).get("at", "")[:10] == day
                   or (r.get("picked_up_at") or "")[:10] == day]
        start, end = f"{day}T00:00:00-0000", f"{day}T23:59:59-0000"
        ts = self.pp.transactions(start, end)
        listed = {t["transaction_info"]["transaction_id"] for t in ts.body.get("transaction_details", [])} if ts.ok else set()
        rows = []
        for r in rentals:
            for kind, cid in (("fee", r.get("fee_capture_id")), ("damage", r.get("settle_capture_id"))):
                if not cid:
                    continue
                if cid in listed:
                    rows.append({"rental": r["id"], "kind": kind, "id": cid, "match": "match", "via": "transaction_search"})
                elif ts.ok:
                    rows.append({"rental": r["id"], "kind": kind, "id": cid, "match": "pending", "via": "transaction_search"})
                else:  # Transaction Search unavailable on this app: read the capture back instead
                    c = self.pp.get_capture(cid, r["id"])
                    rows.append({"rental": r["id"], "kind": kind, "id": cid, "via": "read_back",
                                 "match": "match" if c.body.get("status") == "COMPLETED" else "mismatch"})
            st = r.get("settlement") or {}
            if st.get("void"):
                rb = self.pp.get_authorization(r["authorization_id"], r["id"])
                rows.append({"rental": r["id"], "kind": "void", "id": r["authorization_id"], "via": "read_back",
                             "match": "match" if rb.body.get("status") == "VOIDED" else "mismatch"})
        return {"date": day, "transaction_search_status": ts.status, "transaction_search_issue": ts.issue,
                "listed": len(listed), "rows": rows,
                "summary": {k: sum(1 for x in rows if x["match"] == k) for k in ("match", "pending", "mismatch")}}

    def cron_daily(self) -> dict:
        out: dict[str, list] = {"reauth": [], "expiry_void": [], "judge_void": [], "fines": [], "stale_void": []}
        for shop_id in tariff.shops():
            for r in self.shop_rentals(shop_id, 200):
                if r.get("stale_hold"):
                    out["stale_void"].append(self.retry_stale_void(r["id"]))
                age_days = age_s(r.get("auth_created_at")) / 86400
                if rules.needs_reauth(r["state"], age_days, bool(r.get("reauthorized_at"))):
                    out["reauth"].append(self.reauthorize(r["id"]).get("reauth_method"))
                elif rules.expiry_guard_due(r["state"], age_days) and not r.get("settlement"):
                    self.settle(r["id"], None, force=True)
                    out["expiry_void"].append(r["id"])
        out["judge_void"] = self.judge_void_sweep()
        for fid in self.db.zrangebyscore("fines:due", 0, time.time()):
            out["fines"].append(self.capture_fine(fid).get("status"))
        out["close"] = self.daily_close((now() - timedelta(days=1)).date().isoformat())["summary"]
        return out

    # ------------------------------------------------------------------------------------------
    # 6. judge path
    # ------------------------------------------------------------------------------------------
    def staged_manifest(self) -> dict | None:
        p = STAGED / "judge.json"
        return json.loads(p.read_text()) if p.exists() else None

    def judge_void_sweep(self) -> list[str]:
        done = []
        for rid in self.db.zrangebyscore("judge:open", 0, time.time() - JUDGE_VOID_AFTER_S):
            try:
                r = self.get(rid)
                if not r.get("settlement") and r["state"] in rules.OPEN_HOLD_STATES:
                    self.settle(rid, None, force=True)
                    done.append(rid)
            except ServiceError:
                pass
            self.db.zrem("judge:open", rid)
        return done

    def mint_judge(self, ip: str) -> dict:
        """A FRESH rental per visit: merchant-initiated AUTHORIZE on a pool wallet (failover on any 4xx),
        fee captured from the hold, the staged baseline cloned; opens on the shop's return screen."""
        hour = now().strftime("%Y%m%d%H")
        if self.db.incr(f"rl:judge:{hashlib.sha256(ip.encode()).hexdigest()[:16]}:{hour}", ex=3600) > 12 or \
                self.db.incr(f"rl:judge:all:{now().strftime('%Y%m%d')}", ex=86400) > 300:
            raise ServiceError(429, "RATE_LIMITED", "too many judge rentals from here this hour; try again later")
        self.judge_void_sweep()
        if not self.s.judge_vault_ids:
            raise ServiceError(503, "NO_JUDGE_POOL", "judge wallet pool not configured — use the full path")
        n = self.db.incr("judge:seq")
        rid = f"R-JUDGE-{n}"
        r = self.create_rental("shop-demo", "veh-01", 1, kind="judge", rid=rid)
        auth, vid, last = None, None, None
        for vid in self.s.judge_vault_ids:
            res = self.pp.create_vault_order(rid, vid, r["authorized_cents"], "AUTHORIZE",
                                             f"Judge rental {rid}: fee + damage deposit hold", rental_id=rid,
                                             nonce=r["nonce"])
            auth = first_authorization(res.body) if res.ok else None
            last = res
            if auth:
                break
        if not auth:
            raise ServiceError(502, "JUDGE_POOL_FAILED",
                               f"every pool wallet failed (last: {last.issue if last else 'pool is empty'})",
                               debug_id=last.debug_id if last else None)
        r = self.get(rid)
        r["order_id"] = res.body.get("id")
        self._record_auth(r, auth, replaces=None)
        self._to(r, "APPROVED", authorization_id=auth["id"], auth_created_at=iso(), vault_id=vid,
                 vault_revocable=False, payer_email=payer_email(res.body), auth_expires_at=auth.get("expiration_time"))
        self._save(r)
        self.db.zadd("judge:open", time.time(), rid)
        return self.clone_staged(rid)

    def clone_staged(self, rid: str) -> dict:
        """Clone the staged walkaround (real photos of a real scooter, labelled by hand) into a judge rental,
        confirm it as the shared baseline (fee capture + tracking), and stop at RETURNED for the judge's taps.
        Until the staged set exists the rental stops at OUT and the judge can only release the hold."""
        man = self.staged_manifest()
        with self.lock(rid):
            r = self.get(rid)
            if man:
                r["photos"]["pickup"] = man["pickup"]
                r["closeups"] = man.get("closeups", [])
                r["baseline_marks"] = man.get("baseline_marks", [])
                r["staged"] = {"source": man.get("source"), "walkaround": man.get("walkaround")}
            else:
                r["staged"] = None
                for a in ANGLES:
                    r["photos"]["pickup"][str(a)] = {"sha256": None, "angle": a, "phase": "pickup", "placeholder": True}
            r["confirmations"] = {"renter": {"at": iso(), "baseline_sha256": "staged"},
                                  "shop": {"at": iso(), "baseline_sha256": "staged"}}
            r = self._handover(r)
            if man:
                r["photos"]["return"] = man["return"]
                self._to(r, "RETURNED", returned_at=iso())
            return self._save(r)

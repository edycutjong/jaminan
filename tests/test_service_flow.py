"""The whole rental through the service with an in-memory PayPal and a scripted model: approval →
baseline → return → claims → settle, plus every refusal on the way."""
import pytest

from jaminan import gate
from jaminan.config import Settings
from jaminan.service import Service, ServiceError
from jaminan.store import MemoryStore
from tests.fakes import FakePayPal, ScriptedVision, frame_bytes

BENCH = "qwen-bench-pinned"


def make(vision=None, **env):
    import os
    old = dict(os.environ)
    os.environ.update({"JAMINAN_BENCHMARKED_MODEL": BENCH, "APP_URL": "https://jaminan.test", **env})
    try:
        s = Settings()
    finally:
        os.environ.clear(); os.environ.update(old)
    return Service(s, MemoryStore(), FakePayPal(), vision or ScriptedVision())


def to_out(svc, glare_angle=None, closeup=False):
    r = svc.create_rental("shop-demo", "veh-01", 2)
    rid, k = r["id"], r["keys"]
    svc.approve(rid)
    svc.authorize(rid)
    for a in range(1, 9):
        g = (320, 240, 320, 240) if a == glare_angle else None
        assert svc.add_photo(rid, k["renter"], "pickup", a, frame_bytes(a, g))["accepted"]
    if closeup:
        svc.add_photo(rid, k["renter"], "pickup_closeup", 3, frame_bytes(30))
    svc.premark(rid, k["renter"])
    svc.confirm_baseline(rid, k["renter"])
    r = svc.confirm_baseline(rid, k["shop"])
    assert r["state"] == "OUT"
    return rid, k


def to_returned(svc, **kw):
    rid, k = to_out(svc, **kw)
    for a in range(1, 9):
        assert svc.add_photo(rid, k["shop"], "return", a, frame_bytes(100 + a))["accepted"]
    svc.complete_return(rid, k["shop"])
    return rid, k


def test_one_approval_then_fee_capture_and_tracking_at_handover():
    svc = make()
    rid, k = to_out(svc)
    r = svc.get(rid)
    assert r["fee_captured_cents"] == 3000 and r["auth_status"] == "PARTIALLY_CAPTURED"
    assert r["tracking_number"] == f"JMN-{rid}-{r['baseline_sha256'][:8]}" and r["vault_id"] == "vault-1"
    actions = [c["action"] for c in svc.calls(rid)]
    assert actions[:3] == ["order.create", "order.get", "order.authorize"]
    assert "auth.capture.fee" in actions and "order.track" in actions


def test_the_devastating_query():
    """Shop confirms a suggested crack, taps an old dent and a glared scuff → one line priced, two refused."""
    vision = ScriptedVision(
        suggestions={2: [{"part": "mirror_housing", "damage_class": "crack", "bbox": [400, 300, 120, 120], "confidence": .9}]},
        premarks={3: [{"part": "side_panel", "damage_class": "dent", "bbox": [450, 450, 100, 100], "confidence": .8}]},
        claims={(3, "side_panel", "dent"): {"visible_at_pickup": True},
                (5, "rear_panel", "scuff"): {"pickup_comparable": False}})
    svc = make(vision)
    rid, k = to_returned(svc, glare_angle=5, closeup=True)
    r = svc.suggest(rid, k["shop"])
    s = r["suggestions"][0]
    assert s["status"] == "shown"
    l1 = svc.claim(rid, k["shop"], 2, s["bbox_return"], "mirror_housing", "crack", suggestion_id=s["id"])
    l2 = svc.claim(rid, k["shop"], 3, [0.45, 0.45, 0.1, 0.1], "side_panel", "dent")
    l3 = svc.claim(rid, k["shop"], 5, [0.30, 0.30, 0.1, 0.1], "rear_panel", "scuff")
    assert l1["finding"]["disposition"] == "chargeable" and l1["finding"]["price_cents"] == 1800
    assert l2["answer"] == "visible at pickup — cannot be charged"
    assert l3["finding"]["disposition"] == "not_comparable"
    assert vision.calls.count(("claim", 3, "side_panel", "dent", 1)) == 1  # located renter close-up sent along
    svc.propose(rid, k["shop"])
    svc.decide_line(rid, k["renter"], l1["finding"]["id"], "accepted")
    with pytest.raises(ServiceError):
        svc.decide_line(rid, k["renter"], l2["finding"]["id"], "accepted")
    r = svc.settle(rid, k["renter"])
    assert r["state"] == "SETTLED" and r["settlement"]["capture_cents"] == 1800
    assert r["settlement"]["auth_read_back"] == "CAPTURED" and r["settlement"]["released_cents"] == 8200
    again = svc.settle(rid, k["renter"])  # replay is a no-op
    assert again["settlement"] == r["settlement"]
    final = [c for c in svc.calls(rid) if c["action"] == "auth.capture.final"]
    assert len(final) == 1


def test_clean_return_is_one_tap_release():
    svc = make()
    rid, k = to_returned(svc)
    r = svc.release(rid, k["shop"])
    assert r["state"] == "RELEASED" and r["settlement"]["auth_read_back"] == "VOIDED"
    assert r["settlement"]["released_cents"] == 10000


def test_contested_line_becomes_an_itemized_invoice_and_the_hold_is_released():
    svc = make()
    rid, k = to_returned(svc)
    l = svc.claim(rid, k["shop"], 1, [0.4, 0.4, 0.1, 0.1], "front_fairing", "dent")["finding"]
    svc.propose(rid, k["shop"])
    svc.decide_line(rid, k["renter"], l["id"], "contested")
    r = svc.settle(rid, k["renter"])
    assert r["state"] == "INVOICED" and r["settlement"]["void"]
    assert r["invoice"]["items"][0]["amount_cents"] == 4500 and r["invoice"]["send_status"] == 200


def test_off_bench_model_can_never_charge():
    svc = make(ScriptedVision(model="qwen3.8-max"))
    rid, k = to_returned(svc)
    f = svc.claim(rid, k["shop"], 1, [0.4, 0.4, 0.1, 0.1], "front_fairing", "dent")
    assert f["finding"]["disposition"] == "comparison_unavailable"
    assert f["answer"] == "comparison unavailable — nothing charged from the hold"


def test_model_timeout_charges_nothing():
    svc = make(ScriptedVision(fail=True))
    rid, k = to_returned(svc)
    f = svc.claim(rid, k["shop"], 1, [0.4, 0.4, 0.1, 0.1], "front_fairing", "dent")["finding"]
    assert f["disposition"] == "comparison_unavailable" and f["price_cents"] is None


def test_without_a_pinned_benchmark_nothing_is_chargeable():
    svc = make(JAMINAN_BENCHMARKED_MODEL="")
    rid, k = to_returned(svc)
    assert svc.claim(rid, k["shop"], 1, [0.4, 0.4, 0.1, 0.1], "front_fairing", "dent")["finding"]["disposition"] \
        == "comparison_unavailable"


def test_roles_are_enforced():
    svc = make()
    rid, k = to_returned(svc)
    with pytest.raises(ServiceError) as e:
        svc.claim(rid, k["renter"], 1, [0.4, 0.4, 0.1, 0.1], "front_fairing", "dent")
    assert e.value.status == 403
    l = svc.claim(rid, k["shop"], 1, [0.4, 0.4, 0.1, 0.1], "front_fairing", "dent")["finding"]
    svc.propose(rid, k["shop"])
    with pytest.raises(ServiceError):
        svc.decide_line(rid, k["shop"], l["id"], "accepted")      # only the renter accepts
    with pytest.raises(ServiceError):
        svc.settle(rid, k["shop"])                               # only the renter settles
    with pytest.raises(ServiceError):
        svc.settle(rid, "guess")


def test_claims_must_come_from_the_tariff_list():
    svc = make()
    rid, k = to_returned(svc)
    with pytest.raises(ServiceError) as e:
        svc.claim(rid, k["shop"], 1, [0.4, 0.4, 0.1, 0.1], "seat", "crack")
    assert e.value.code == "NOT_IN_TARIFF"


def test_only_the_renter_removes_model_premarks_and_the_shop_only_adds():
    svc = make(ScriptedVision(premarks={3: [{"part": "side_panel", "damage_class": "dent", "bbox": [1, 1, 50, 50]}]}))
    r = svc.create_rental("shop-demo", "veh-01", 1)
    rid, k = r["id"], r["keys"]
    svc.approve(rid); svc.authorize(rid)
    for a in range(1, 9):
        svc.add_photo(rid, k["renter"], "pickup", a, frame_bytes(a))
    r = svc.premark(rid, k["renter"])
    mid = r["baseline_marks"][0]["id"]
    with pytest.raises(ServiceError) as e:
        svc.edit_mark(rid, k["shop"], "remove", {"id": mid})
    assert e.value.code == "ONLY_RENTER_REMOVES_MODEL_MARKS"
    svc.edit_mark(rid, k["shop"], "add", {"angle": 5, "part": "rear_panel", "damage_class": "scuff"})
    shop_mark = svc.get(rid)["baseline_marks"][-1]["id"]
    with pytest.raises(ServiceError):
        svc.edit_mark(rid, k["renter"], "remove", {"id": shop_mark})
    svc.edit_mark(rid, k["renter"], "remove", {"id": mid})


def test_baseline_needs_all_angles_both_parties_and_no_pending_retake():
    svc = make()
    r = svc.create_rental("shop-demo", "veh-01", 1)
    rid, k = r["id"], r["keys"]
    svc.approve(rid); svc.authorize(rid)
    for a in range(1, 8):
        svc.add_photo(rid, k["renter"], "pickup", a, frame_bytes(a))
    with pytest.raises(ServiceError):
        svc.confirm_baseline(rid, k["renter"])
    svc.add_photo(rid, k["renter"], "pickup", 8, frame_bytes(8))
    svc.request_retake(rid, k["shop"], 5)
    with pytest.raises(ServiceError) as e:
        svc.confirm_baseline(rid, k["renter"])
    assert e.value.code == "RETAKE_PENDING"
    svc.add_photo(rid, k["renter"], "pickup", 5, frame_bytes(55))
    assert svc.confirm_baseline(rid, k["renter"])["state"] == "APPROVED"   # waits for the shop
    assert svc.confirm_baseline(rid, k["shop"])["state"] == "OUT"


def test_blurry_frame_is_rejected_and_not_stored():
    from PIL import Image, ImageFilter
    import io
    svc = make()
    r = svc.create_rental("shop-demo", "veh-01", 1)
    svc.approve(r["id"]); svc.authorize(r["id"])
    img = Image.open(io.BytesIO(frame_bytes(1))).filter(ImageFilter.GaussianBlur(12))
    b = io.BytesIO(); img.save(b, "JPEG")
    res = svc.add_photo(r["id"], r["keys"]["renter"], "pickup", 1, b.getvalue())
    assert not res["accepted"] and res["gate"]["reason"] == "blurry"
    assert svc.get(r["id"])["photos"]["pickup"] == {}


def test_expiry_guard_releases_an_unsettled_return():
    svc = make()
    rid, k = to_returned(svc)
    svc.claim(rid, k["shop"], 1, [0.4, 0.4, 0.1, 0.1], "front_fairing", "dent")
    r = svc.settle(rid, None, force=True)       # I5: nobody acted → release; nothing unanswered is invoiced
    assert r["settlement"]["void"] and r["invoice"] is None


def test_reauthorize_refused_falls_back_to_mit_resecure_and_voids_the_old_hold():
    svc = make()
    rid, k = to_out(svc)
    old = svc.get(rid)["authorization_id"]
    r = svc.reauthorize(rid)
    assert r["reauth_method"] == "mit_resecure" and r["authorization_id"] != old
    assert r["authorizations"][-1]["replaces"] == old
    assert svc.pp.auths[old]["status"] == "VOIDED"


def test_judge_rental_fails_over_across_the_pool_and_never_deletes_a_pool_wallet():
    svc = make(JUDGE_VAULT_IDS="bad-1,vault-ok")
    r = svc.mint_judge("1.2.3.4")
    assert r["id"].startswith("R-JUDGE-") and r["vault_id"] == "vault-ok" and r["state"] == "OUT"
    out = svc.revoke_vault(r["id"], r["keys"]["renter"])
    assert out["vault_revoke"]["shown_only"] and out["vault_revoke"]["request"]["method"] == "DELETE"
    assert not [c for c in svc.calls(r["id"]) if c["action"] == "vault.delete"]
    rel = svc.release(r["id"], r["keys"]["shop"])
    assert rel["settlement"]["auth_read_back"] == "VOIDED"


def test_judge_rate_limit():
    svc = make(JUDGE_VAULT_IDS="vault-ok")
    for _ in range(12):
        svc.mint_judge("9.9.9.9")
    with pytest.raises(ServiceError) as e:
        svc.mint_judge("9.9.9.9")
    assert e.value.status == 429


def test_fine_is_quoted_then_captured_on_the_saved_wallet_after_the_contest_window():
    svc = make()
    rid, k = to_returned(svc)
    svc.release(rid, k["shop"])
    svc.db.set_json(f"rental:{rid}", {**svc.get(rid), "returned_at": "2100-01-01T00:00:00+00:00"})
    f = svc.create_fine(rid, k["shop"], frame_bytes(9), 900000)
    assert f["quote"]["chargeable"] and f["quote"]["capped"]
    assert svc.capture_fine(f["id"])["status"] == "notified"       # never inside the 72 h contest window
    svc.db.set_json(f"fine:{f['id']}", {**f, "contest_until": "2000-01-01T00:00:00+00:00"})
    out = svc.capture_fine(f["id"])
    assert out["status"] == "captured" and out["capture_id"] and out["capture_status"] == "COMPLETED"


def test_paypal_5xx_is_retried_with_the_same_request_id():
    svc = make()
    rid, k = to_returned(svc)
    svc.pp.fail_next = [500]
    r = svc.release(rid, k["shop"])
    voids = [c for c in svc.calls(rid) if c["action"] == "auth.void"]
    assert r["settlement"]["auth_read_back"] == "VOIDED"
    assert len(voids) >= 1 and len({c["request_id"] for c in voids}) == 1


def test_a_full_path_approval_that_returns_a_pool_wallet_is_never_deleted():
    svc = make(JUDGE_VAULT_IDS="vault-1")          # FakePayPal vaults every approval as vault-1
    r = svc.create_rental("shop-demo", "veh-01", 1)
    svc.approve(r["id"])
    a = svc.authorize(r["id"])
    assert a["vault_id"] == "vault-1" and a["vault_revocable"] is False
    out = svc.revoke_vault(r["id"], r["keys"]["renter"])
    assert out["vault_revoke"]["shown_only"]


def test_daily_close_falls_back_to_read_back_when_transaction_search_is_refused():
    svc = make()
    rid, k = to_returned(svc)
    svc.release(rid, k["shop"])
    svc.pp.fail_next = []
    orig = svc.pp._route
    svc.pp._route = lambda m, p, b: (403, {"name": "NOT_AUTHORIZED"}) if p == "/v1/reporting/transactions" else orig(m, p, b)
    out = svc.daily_close()
    assert out["transaction_search_status"] == 403
    kinds = {(x["kind"], x["via"], x["match"]) for x in out["rows"]}
    assert ("void", "read_back", "match") in kinds and ("fee", "read_back", "match") in kinds


def test_the_renter_cannot_release_and_a_spot_cannot_be_claimed_twice():
    svc = make()
    rid, k = to_returned(svc)
    with pytest.raises(ServiceError) as e:
        svc.release(rid, k["renter"])
    assert e.value.status == 403
    svc.claim(rid, k["shop"], 1, [0.4, 0.4, 0.1, 0.1], "front_fairing", "dent")
    with pytest.raises(ServiceError) as e:
        svc.claim(rid, k["shop"], 1, [0.41, 0.41, 0.1, 0.1], "front_fairing", "dent")
    assert e.value.code == "DUPLICATE_CLAIM"
    svc.claim(rid, k["shop"], 1, [0.41, 0.41, 0.1, 0.1], "front_fairing", "crack")   # another class is another claim


def test_fine_after_the_renter_removed_saved_paypal_arrives_as_an_invoice():
    svc = make()
    rid, k = to_returned(svc)
    svc.release(rid, k["shop"])
    svc.revoke_vault(rid, k["renter"])
    svc.db.set_json(f"rental:{rid}", {**svc.get(rid), "returned_at": "2100-01-01T00:00:00+00:00"})
    f = svc.create_fine(rid, k["shop"], frame_bytes(9), 200000)
    assert f["status"] == "invoiced" and f["invoice_id"]


def test_evidence_pack_needs_a_key_or_its_link_token():
    svc = make()
    rid, k = to_returned(svc)
    with pytest.raises(ServiceError):
        svc.evidence(rid)
    assert svc.evidence(rid, token=svc.get(rid)["evidence_token"])["rental"] == rid
    assert svc.evidence(rid, key=k["renter"])["rental"] == rid


def test_a_lock_is_only_released_by_its_owner():
    svc = make()
    r = svc.create_rental("shop-demo", "veh-01", 1)
    with svc.lock(r["id"]):
        svc.db.set_json(f"lock:{r['id']}", "someone-else", ex=30)   # our lock expired; another request took it
    assert svc.db.get_json(f"lock:{r['id']}") == "someone-else"


def test_capability_keys_are_role_scoped_and_other_rentals_keys_are_refused():
    svc = make()
    rid, k = to_returned(svc)
    other_rid, other_k = to_returned(svc)
    shop_only = [lambda key: svc.release(rid, key), lambda key: svc.claim(rid, key, 1, [0.1, 0.1, 0.1, 0.1], "mirror_housing", "crack")]
    for act in shop_only:
        for bad in (None, "", k["renter"], other_k["shop"], "x" * 24):
            with pytest.raises(ServiceError) as e:
                act(bad)
            assert e.value.status == 403, "the shop's actions need the shop's key for this rental"
    with pytest.raises(ServiceError) as e:
        svc.decide_line(rid, k["shop"], "L1", "accepted")   # the shop can never accept a line on the renter's behalf
    assert e.value.status == 403
    assert svc.get(other_rid)["state"] == "RETURNED" and svc.get(rid)["state"] == "RETURNED"


def test_a_claim_on_an_expired_stored_photo_is_a_410_not_a_crash():
    svc = make()
    rid, k = to_returned(svc)
    r = svc.get(rid)
    svc.db.delete(f"frame:{r['photos']['pickup']['1']['sha256']}")
    with pytest.raises(ServiceError) as e:
        svc.claim(rid, k["shop"], 1, [0.4, 0.4, 0.1, 0.1], "mirror_housing", "crack")
    assert e.value.status == 410 and e.value.code == "FRAME_EXPIRED"


def test_a_refused_void_during_the_resecure_is_kept_and_retried_by_the_daily_job():
    svc = make()
    rid, k = to_out(svc)
    old = svc.get(rid)["authorization_id"]
    orig = svc.pp._route
    svc.pp._route = lambda m, p, b: ((422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "PERMISSION_DENIED"}]})
                                     if p == f"/v2/payments/authorizations/{old}/void" else orig(m, p, b))
    r = svc.reauthorize(rid)
    assert r["reauth_method"] == "mit_resecure" and r["stale_hold"]["authorization_id"] == old
    assert svc.pp.auths[old]["status"] != "VOIDED"
    svc.pp._route = orig
    assert svc.cron_daily()["stale_void"] == ["voided"]
    assert svc.pp.auths[old]["status"] == "VOIDED" and "stale_hold" not in svc.get(rid)


def test_daily_close_reads_a_final_status_back_from_paypal_once():
    svc = make()
    rid, k = to_returned(svc)
    svc.release(rid, k["shop"])
    orig = svc.pp._route
    svc.pp._route = lambda m, p, b: (403, {"name": "NOT_AUTHORIZED"}) if p == "/v1/reporting/transactions" else orig(m, p, b)
    reads = lambda: len([c for c in svc.calls(rid) if c["action"] in ("auth.get", "capture.get")])  # noqa: E731
    first = svc.daily_close()
    n = reads()
    second = svc.daily_close()
    assert reads() == n and first["rows"] == second["rows"] and second["summary"]["mismatch"] == 0


def test_a_tap_box_must_be_four_finite_numbers_and_a_retake_a_real_angle():
    svc = make()
    rid, k = to_returned(svc)
    with pytest.raises(ServiceError) as e:
        svc.claim(rid, k["shop"], 1, [float("nan"), 0.4, 0.1, 0.1], "front_fairing", "dent")
    assert e.value.code == "BAD_TAP"
    r = svc.create_rental("shop-demo", "veh-01", 1)
    svc.approve(r["id"]); svc.authorize(r["id"])
    with pytest.raises(ServiceError) as e:
        svc.request_retake(r["id"], r["keys"]["shop"], 9)
    assert e.value.code == "BAD_ANGLE"


def _fined(svc):
    rid, k = to_returned(svc)
    svc.release(rid, k["shop"])
    svc.db.set_json(f"rental:{rid}", {**svc.get(rid), "returned_at": "2100-01-01T00:00:00+00:00"})
    return rid, k, svc.create_fine(rid, k["shop"], frame_bytes(9), 900000)


def test_a_contest_is_stored_before_its_invoice_calls_so_the_daily_debit_skips_it():
    svc = make()
    rid, k, f = _fined(svc)
    seen = {}

    def invoice(r, fine, name):
        seen["stored"] = svc.db.get_json(f"fine:{fine['id']}")["status"]
        return "INV2-TEST"
    svc._fine_invoice = invoice
    out = svc.contest_fine(rid, k["renter"], f["id"])
    assert seen["stored"] == "contested_invoiced" and out["invoice_id"] == "INV2-TEST"
    svc.db.set_json(f"fine:{f['id']}", {**out, "contest_until": "2000-01-01T00:00:00+00:00"})
    assert svc.capture_fine(f["id"])["status"] == "contested_invoiced"
    assert not [c for c in svc.calls(rid) if c["action"] == "order.create.mit.capture"]


def test_a_pending_fine_capture_is_not_reported_as_captured():
    svc = make()
    rid, k, f = _fined(svc)
    svc.db.set_json(f"fine:{f['id']}", {**f, "contest_until": "2000-01-01T00:00:00+00:00"})
    orig = svc.pp._route

    def pending(m, p, b):
        st, body = orig(m, p, b)
        for pu in body.get("purchase_units") or []:
            for c in (pu.get("payments") or {}).get("captures") or []:
                c["status"] = "PENDING"
        return st, body
    svc.pp._route = pending
    out = svc.capture_fine(f["id"])
    assert out["status"] == "capture_pending" and out["capture_status"] == "PENDING"


def test_a_pickup_photo_that_lands_after_the_handover_is_refused(monkeypatch):
    svc = make()
    r = svc.create_rental("shop-demo", "veh-01", 1)
    rid, k = r["id"], r["keys"]
    svc.approve(rid); svc.authorize(rid)
    real = gate.check

    def slow_gate(data, thresholds=None):     # the handover completes while this upload is in the gate
        out = real(data, thresholds)
        svc.db.set_json(f"rental:{rid}", {**svc.get(rid), "state": "OUT"})
        return out
    monkeypatch.setattr(gate, "check", slow_gate)
    with pytest.raises(ServiceError) as e:
        svc.add_photo(rid, k["renter"], "pickup", 1, frame_bytes(1))
    assert e.value.code == "BASELINE_LOCKED" and svc.get(rid)["photos"]["pickup"] == {}


def test_premark_results_never_land_on_a_baseline_that_changed_during_the_model_call():
    svc = make()
    r = svc.create_rental("shop-demo", "veh-01", 1)
    rid, k = r["id"], r["keys"]
    svc.approve(rid); svc.authorize(rid)
    for a in range(1, 9):
        svc.add_photo(rid, k["renter"], "pickup", a, frame_bytes(a))
    real = svc.vision.premark

    def premark(pickup, angle):               # angle 1 is retaken while the model looks at the old frame
        if angle == 8:
            svc.add_photo(rid, k["renter"], "pickup", 1, frame_bytes(77))
        return real(pickup, angle)
    svc.vision.premark = premark
    with pytest.raises(ServiceError) as e:
        svc.premark(rid, k["renter"])
    assert e.value.code == "PHOTOS_CHANGED" and not [m for m in svc.get(rid)["baseline_marks"] if m["source"] == "model"]

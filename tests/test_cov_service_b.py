"""Service refusals and rare branches, part B: pre-marks, retakes, baseline, return, suggestions, claims, settle."""

from jaminan.paypal import Resp
from tests.fakes import ScriptedVision, frame_bytes
from tests.test_cov_service_a import approved, code, draft
from tests.test_service_flow import make, to_out, to_returned

BAD = Resp(500, {"name": "INTERNAL_SERVER_ERROR"}, "dbg", "x", None, 1)


def pickups(svc, rid, k):
    svc.authorize(rid)
    for a in range(1, 9):
        svc.add_photo(rid, k["renter"], "pickup", a, frame_bytes(a))


def test_edit_mark_guards_key_state_target_and_action():
    svc = make()
    rid, k = approved(svc)
    svc.authorize(rid)
    mark = {"angle": 2, "part": "mirror_housing", "damage_class": "crack", "bbox": [0.4, 0.4, 0.1, 0.1]}
    assert code(svc.edit_mark, rid, "bogus", "add", mark) == "FORBIDDEN"
    assert code(svc.edit_mark, rid, k["shop"], "remove", {"id": "nope"}) == "NO_MARK"
    assert code(svc.edit_mark, rid, k["shop"], "explode", mark) == "BAD_ACTION"
    added = svc.edit_mark(rid, k["shop"], "add", mark)
    assert added["baseline_marks"][0]["id"] == "S1"
    pickups(svc, rid, k)
    svc.confirm_baseline(rid, k["renter"])
    svc.confirm_baseline(rid, k["shop"])
    assert code(svc.edit_mark, rid, k["shop"], "add", mark) == "BASELINE_LOCKED"


def test_retake_and_confirm_guards_on_a_locked_or_incomplete_baseline():
    svc = make()
    rid, k = approved(svc)
    pickups(svc, rid, k)
    assert code(svc.confirm_baseline, rid, "bogus") == "FORBIDDEN"
    svc.confirm_baseline(rid, k["renter"])
    svc.confirm_baseline(rid, k["shop"])
    assert code(svc.request_retake, rid, k["shop"], 1) == "BASELINE_LOCKED"
    assert code(svc.confirm_baseline, rid, k["shop"]) == "BASELINE_LOCKED"


def test_confirm_refuses_a_baseline_that_changed_between_the_two_taps():
    svc = make()
    rid, k = approved(svc)
    pickups(svc, rid, k)
    svc.confirm_baseline(rid, k["renter"])
    r = svc.get(rid)
    r["confirmations"]["renter"]["baseline_sha256"] = "stale"
    svc._save(r)
    after = svc.confirm_baseline(rid, k["shop"])
    assert after["state"] == "APPROVED" and list(after["confirmations"]) == ["shop"]


def test_the_fee_capture_failing_at_handover_is_a_502_and_leaves_the_rental_unconfirmed(monkeypatch):
    svc = make()
    rid, k = approved(svc)
    pickups(svc, rid, k)
    svc.confirm_baseline(rid, k["renter"])
    monkeypatch.setattr(svc.pp, "capture", lambda *a, **kw: BAD)
    assert code(svc.confirm_baseline, rid, k["shop"]) == "PAYPAL_CAPTURE_FAILED"
    assert svc.get(rid)["state"] == "APPROVED"


def test_return_guards_key_and_missing_angles():
    svc = make()
    rid, k = to_out(svc)
    assert code(svc.complete_return, rid, "bogus") == "FORBIDDEN"
    assert code(svc.complete_return, rid, k["shop"]) == "ANGLES_MISSING"


def test_suggest_claim_and_settle_refuse_a_rental_that_is_not_returned():
    svc = make()
    rid, k = to_out(svc)
    assert code(svc.suggest, rid, k["shop"]) == "NOT_RETURNED"
    assert code(svc.claim, rid, k["shop"], 2, [0.4, 0.4, 0.1, 0.1], "mirror_housing", "crack") == "NOT_RETURNED"
    assert code(svc.settle, rid, k["renter"]) == "NOT_PROPOSED"


def test_a_claim_that_becomes_invalid_while_the_model_runs_is_refused():
    svc = make()
    rid, k = to_returned(svc)
    real = svc.vision.claim

    def settle_meanwhile(*a, **kw):
        r = svc.get(rid)
        r["state"] = "DRAFT"
        svc._save(r)
        return real(*a, **kw)

    svc.vision.claim = settle_meanwhile
    assert code(svc.claim, rid, k["shop"], 2, [0.4, 0.4, 0.1, 0.1], "mirror_housing", "crack") == "NOT_RETURNED"


def test_dismissing_a_suggestion_marks_it_and_an_unknown_id_is_a_404():
    vision = ScriptedVision(suggestions={2: [{"part": "mirror_housing", "damage_class": "crack",
                                              "bbox": [400, 300, 120, 120], "confidence": .9}]})
    svc = make(vision)
    rid, k = to_returned(svc)
    s = svc.suggest(rid, k["shop"])["suggestions"][0]
    assert code(svc.dismiss_suggestion, rid, k["shop"], "S-nope") == "NO_SUGGESTION"
    assert code(svc.dismiss_suggestion, rid, "bogus", s["id"]) == "FORBIDDEN"
    out = svc.dismiss_suggestion(rid, k["shop"], s["id"])
    assert [x["status"] for x in out["suggestions"]] == ["dismissed"]


def test_confirming_the_second_of_two_suggestions_leaves_the_first_shown():
    one = {"part": "mirror_housing", "damage_class": "crack", "bbox": [400, 300, 120, 120], "confidence": .9}
    two = {"part": "rear_panel", "damage_class": "scuff", "bbox": [300, 300, 120, 120], "confidence": .9}
    svc = make(ScriptedVision(suggestions={2: [one], 5: [two]}))
    rid, k = to_returned(svc)
    shown = {s["angle"]: s for s in svc.suggest(rid, k["shop"])["suggestions"]}
    svc.claim(rid, k["shop"], 5, shown[5]["bbox_return"], "rear_panel", "scuff", suggestion_id=shown[5]["id"])
    status = {s["angle"]: s["status"] for s in svc.get(rid)["suggestions"]}
    assert status[5] == "confirmed" and status[2] == "shown"


def test_decide_and_settle_guards():
    svc = make()
    rid, k = to_returned(svc)
    f = svc.claim(rid, k["shop"], 2, [0.4, 0.4, 0.1, 0.1], "mirror_housing", "crack")["finding"]
    assert code(svc.decide_line, rid, k["renter"], f["id"], "maybe") == "BAD_DECISION"
    assert code(svc.decide_line, rid, k["renter"], f["id"], "accepted") == "NOT_PROPOSED"
    svc.propose(rid, k["shop"])
    assert code(svc.decide_line, rid, k["renter"], "L99", "accepted") == "NO_LINE"
    assert code(svc.settle, rid, k["renter"]) == "SETTLE_BLOCKED"   # a chargeable line nobody answered


def test_settle_refuses_a_rental_that_cannot_hold_a_settlement():
    svc = make()
    rid, k = draft(svc)
    assert code(svc.settle, rid, k["renter"]) == "NOT_SETTLEABLE"

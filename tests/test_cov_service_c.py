"""Service rare branches, part C: lock waits, settle/invoice failures, release, vault revoke, reauthorize, stale voids."""
import pytest

from jaminan.paypal import Resp
from jaminan.service import ServiceError
from tests.test_cov_service_a import code
from tests.test_service_flow import make, to_out, to_returned

BAD = Resp(500, {"name": "INTERNAL_SERVER_ERROR"}, "dbg", "x", None, 1)
REFUSED = Resp(422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "REAUTHORIZATION_TOO_SOON"}]}, "dbg", "x", None, 1)


def contested(svc):
    rid, k = to_returned(svc)
    f = svc.claim(rid, k["shop"], 1, [0.4, 0.4, 0.1, 0.1], "front_fairing", "dent")["finding"]
    svc.propose(rid, k["shop"])
    svc.decide_line(rid, k["renter"], f["id"], "contested")
    return rid, k


def test_a_waiting_request_sleeps_between_tries_before_giving_up(monkeypatch):
    svc = make()
    rid, _ = to_out(svc)
    svc.db.set_json(f"lock:{rid}", "other", ex=60)
    naps = []
    monkeypatch.setattr("jaminan.service.time.sleep", naps.append)
    with pytest.raises(ServiceError) as e:
        with svc.lock(rid, wait_s=0.01):
            pass
    assert e.value.code == "BUSY" and naps and set(naps) == {0.15}


def test_a_final_capture_refused_by_paypal_is_a_502_and_the_rental_stays_proposed(monkeypatch):
    svc = make()
    rid, k = to_returned(svc)
    f = svc.claim(rid, k["shop"], 2, [0.4, 0.4, 0.1, 0.1], "mirror_housing", "crack")["finding"]
    svc.propose(rid, k["shop"])
    svc.decide_line(rid, k["renter"], f["id"], "accepted")
    monkeypatch.setattr(svc.pp, "capture", lambda *a, **kw: BAD)
    assert code(svc.settle, rid, k["renter"]) == "PAYPAL_CAPTURE_FAILED"
    assert svc.get(rid)["state"] == "PROPOSED"


def test_a_refused_void_on_release_is_a_502(monkeypatch):
    svc = make()
    rid, k = to_returned(svc)
    monkeypatch.setattr(svc.pp, "void", lambda *a, **kw: BAD)
    assert code(svc.release, rid, k["shop"]) == "PAYPAL_VOID_FAILED"


def test_release_refuses_when_there_are_priced_lines():
    svc = make()
    rid, k = to_returned(svc)
    svc.claim(rid, k["shop"], 2, [0.4, 0.4, 0.1, 0.1], "mirror_housing", "crack")
    assert code(svc.release, rid, k["shop"]) == "HAS_LINES"


def test_an_invoice_paypal_refuses_is_recorded_without_a_send_or_a_state_change(monkeypatch):
    svc = make()
    monkeypatch.setattr(svc.pp, "create_invoice", lambda *a, **kw: BAD)
    rid, k = contested(svc)
    r = svc.settle(rid, k["renter"])
    assert r["state"] == "RELEASED" and r["invoice"]["id"] is None and r["invoice"]["create_status"] == 500
    assert "send_status" not in r["invoice"]


def test_an_invoice_whose_qr_fails_is_still_sent_without_a_qr(monkeypatch):
    svc = make()
    monkeypatch.setattr(svc.pp, "invoice_qr", lambda *a, **kw: BAD)
    rid, k = contested(svc)
    r = svc.settle(rid, k["renter"])
    assert r["state"] == "INVOICED" and r["invoice"]["qr_status"] == 500 and "qr_png_b64" not in r["invoice"]
    assert r["invoice"]["send_status"] == 200


def test_revoke_vault_without_a_saved_wallet_and_with_a_paypal_refusal(monkeypatch):
    svc = make()
    rid, k = to_out(svc)
    r = svc.get(rid)
    r.update(vault_id=None)
    svc._save(r)
    assert code(svc.revoke_vault, rid, k["renter"]) == "NO_VAULT"
    r = svc.get(rid)
    r.update(vault_id="vault-1", vault_revocable=True)
    svc._save(r)
    monkeypatch.setattr(svc.pp, "delete_payment_token", lambda *a, **kw: BAD)
    out = svc.revoke_vault(rid, k["renter"])
    assert out["vault_revoke"]["status"] == 500 and out.get("vault_status") != "DELETED"
    assert svc.db.get_json("vault:deleted:vault-1") is None


def test_reauthorize_refuses_a_rental_with_no_open_hold():
    svc = make()
    rid = svc.create_rental("shop-demo", "veh-01", 2)["id"]
    assert code(svc.reauthorize, rid) == "NOT_OPEN"


def test_a_successful_reauthorize_records_the_new_hold_in_the_same_lineage(monkeypatch):
    svc = make()
    rid, _ = to_out(svc)
    old = svc.get(rid)["authorization_id"]
    monkeypatch.setattr(svc.pp, "reauthorize", lambda *a, **kw: Resp(
        201, {"id": "NEWAUTH", "status": "CREATED", "expiration_time": "2026-12-01T00:00:00Z"}, "dbg", "auth.reauthorize", None, 1))
    r = svc.reauthorize(rid)
    assert r["reauth_method"] == "reauthorize" and r["authorization_id"] == "NEWAUTH"
    assert r["auth_expires_at"] == "2026-12-01T00:00:00Z" and r["authorizations"][-1]["replaces"] == old
    assert svc.reauthorize(rid)["authorization_id"] == "NEWAUTH"     # once only


def test_a_refused_reauthorize_with_a_failing_mit_fallback_keeps_the_old_hold(monkeypatch):
    svc = make()
    rid, _ = to_out(svc)
    old = svc.get(rid)["authorization_id"]
    monkeypatch.setattr(svc.pp, "reauthorize", lambda *a, **kw: REFUSED)
    monkeypatch.setattr(svc.pp, "create_vault_order", lambda *a, **kw: BAD)
    r = svc.reauthorize(rid)
    assert r["authorization_id"] == old and r["reauth_error"]["reauthorize"] == "REAUTHORIZATION_TOO_SOON"
    assert "mit" in r["reauth_error"]


def test_a_refused_reauthorize_on_a_rental_with_no_wallet_records_the_error(monkeypatch):
    svc = make()
    rid, _ = to_out(svc)
    r = svc.get(rid)
    r["vault_id"] = None
    svc._save(r)
    monkeypatch.setattr(svc.pp, "reauthorize", lambda *a, **kw: REFUSED)
    out = svc.reauthorize(rid)
    assert out["reauth_error"] == {"reauthorize": "REAUTHORIZATION_TOO_SOON", "at": out["reauth_error"]["at"]}


def test_a_stale_void_is_retried_until_paypal_accepts_it(monkeypatch):
    svc = make()
    rid, _ = to_out(svc)
    assert svc.retry_stale_void(rid) == "none"
    r = svc.get(rid)
    r["stale_hold"] = {"authorization_id": r["authorization_id"], "issue": "X", "debug_id": "d", "at": "t"}
    svc._save(r)
    svc.db.zadd("holds:stale", 1, rid)
    monkeypatch.setattr(svc.pp, "void", lambda *a, **kw: BAD)
    assert svc.retry_stale_void(rid) == "open"
    assert svc.get(rid)["stale_hold"]["retried_at"] and rid in svc.db.zrange("holds:stale")
    monkeypatch.undo()
    assert svc.retry_stale_void(rid) == "voided"
    assert "stale_hold" not in svc.get(rid) and rid not in svc.db.zrange("holds:stale")


def test_a_fine_cannot_attach_to_a_rental_that_is_still_out():
    svc = make()
    rid, k = to_out(svc)
    assert code(svc.create_fine, rid, k["shop"], b"x", 900000) == "RENTAL_OPEN"

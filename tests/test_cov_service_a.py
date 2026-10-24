"""Service refusals and rare branches, part A: lookup, locks, views, create/approve/authorize, photos, premark."""
import pytest

from jaminan import service as svcmod
from jaminan.paypal import Resp
from jaminan.service import ServiceError
from tests.fakes import frame_bytes
from tests.test_service_flow import make, to_out


def code(fn, *a, **k) -> str:
    with pytest.raises(ServiceError) as e:
        fn(*a, **k)
    return e.value.code


def draft(svc, days=2):
    r = svc.create_rental("shop-demo", "veh-01", days)
    return r["id"], r["keys"]


def approved(svc):
    rid, k = draft(svc)
    svc.approve(rid)
    return rid, k


def test_an_unknown_rental_is_a_404():
    assert code(make().get, "R-nope") == "RENTAL_NOT_FOUND"


def test_a_held_lock_turns_the_second_request_into_busy():
    svc = make()
    rid, _ = draft(svc)
    svc.db.set_json(f"lock:{rid}", "someone-else", ex=60)
    with pytest.raises(ServiceError) as e:
        with svc.lock(rid, wait_s=-1):
            pass
    assert e.value.code == "BUSY" and e.value.status == 409


def test_views_name_the_role_and_only_the_shop_gets_the_renter_link():
    svc = make()
    rid, k = draft(svc)
    r = svc.get(rid)
    assert "role" not in svc.view(r, None) and "renter_link" not in svc.view(r, None)
    assert svc.view(r, "renter")["role"] == "renter" and "renter_link" not in svc.view(r, "renter")
    shop = svc.view(r, "shop")
    assert shop["renter_link"].endswith(f"/r/{rid}?k={k['renter']}") and "keys" not in shop


def test_create_refuses_an_unknown_vehicle_and_out_of_range_days():
    svc = make()
    assert code(svc.create_rental, "shop-demo", "veh-nope", 2) == "UNKNOWN_VEHICLE"
    assert code(svc.create_rental, "shop-nope", "veh-01", 2) == "UNKNOWN_VEHICLE"
    assert code(svc.create_rental, "shop-demo", "veh-01", 0) == "BAD_DAYS"
    assert code(svc.create_rental, "shop-demo", "veh-01", 29) == "BAD_DAYS"


def test_approve_twice_is_refused_and_a_paypal_failure_is_a_502(monkeypatch):
    svc = make()
    rid, _ = draft(svc)
    monkeypatch.setattr(svc.pp, "create_authorize_order",
                        lambda *a, **k: Resp(500, {"name": "INTERNAL_SERVER_ERROR"}, "dbg", "order.create", None, 1))
    assert code(svc.approve, rid) == "PAYPAL_ORDER_FAILED"
    monkeypatch.undo()
    svc.approve(rid)
    svc.authorize(rid)
    assert code(svc.approve, rid) == "ALREADY_APPROVED"


def test_authorize_is_idempotent_after_the_state_moved_and_refuses_an_unapproved_order(monkeypatch):
    svc = make()
    rid, _ = approved(svc)
    oid = svc.get(rid)["order_id"]
    svc.pp.orders[oid]["status"] = "CREATED"
    assert code(svc.authorize, rid) == "NOT_APPROVED"
    svc.pp.orders[oid]["status"] = "APPROVED"
    monkeypatch.setattr(svc.pp, "authorize_order",
                        lambda *a, **k: Resp(422, {"name": "UNPROCESSABLE_ENTITY"}, "dbg", "order.authorize", None, 1))
    assert code(svc.authorize, rid) == "PAYPAL_AUTHORIZE_FAILED"
    monkeypatch.undo()
    first = svc.authorize(rid)
    assert svc.authorize(rid) == first   # a reload of the return page lands on the stored state


def test_a_staged_frame_is_served_from_fixtures_when_redis_has_no_copy(tmp_path, monkeypatch):
    svc = make()
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames" / "abc.jpg").write_bytes(b"staged")
    monkeypatch.setattr(svcmod, "STAGED", tmp_path)
    assert svc.frame("abc") == b"staged" and svc.frame("zzz") is None
    assert code(svc.frame_required, "zzz") == "FRAME_EXPIRED"


def test_photo_phase_and_state_guards():
    svc = make()
    rid, k = approved(svc)
    svc.authorize(rid)
    assert code(svc.add_photo, rid, k["renter"], "selfie", 1, frame_bytes(1)) == "BAD_PHASE"
    assert code(svc.add_photo, rid, k["shop"], "return", 1, frame_bytes(1)) == "NOT_OUT"
    svc2 = make()
    rid2, k2 = to_out(svc2)
    assert code(svc2.add_photo, rid2, k2["renter"], "pickup", 1, frame_bytes(1)) == "BASELINE_LOCKED"


def test_premark_guards_state_and_missing_angles():
    svc = make()
    rid, k = draft(svc)
    assert code(svc.premark, rid, k["renter"]) == "BASELINE_LOCKED"
    svc.approve(rid)
    svc.authorize(rid)
    assert code(svc.premark, rid, k["renter"]) == "ANGLES_MISSING"


def test_the_baseline_confirmed_while_the_model_marks_is_refused():
    svc = make()
    rid, k = approved(svc)
    svc.authorize(rid)
    for a in range(1, 9):
        svc.add_photo(rid, k["renter"], "pickup", a, frame_bytes(a))
    real = svc.vision.premark

    def sneaky(pickup, angle):
        r = svc.get(rid)
        r["state"] = "OUT"
        svc._save(r)
        return real(pickup, angle)

    svc.vision.premark = sneaky
    assert code(svc.premark, rid, k["renter"]) == "BASELINE_LOCKED"

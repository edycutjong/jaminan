"""Service rare branches, part D: fines, daily close, the daily job, judge pool and the staged baseline."""
from datetime import timedelta

from jaminan.paypal import Resp
from jaminan.service import ServiceError, iso, now
from tests.test_cov_service_a import code
from tests.test_service_flow import _fined, make, to_out, to_returned

BAD = Resp(500, {"name": "INTERNAL_SERVER_ERROR"}, "dbg", "x", None, 1)


def test_contesting_an_unknown_or_foreign_fine_is_a_404_and_twice_is_refused():
    svc = make()
    rid, k, f = _fined(svc)
    assert code(svc.contest_fine, rid, k["renter"], "F-nope") == "NO_FINE"
    other, ok = to_out(svc)
    assert code(svc.contest_fine, other, ok["renter"], f["id"]) == "NO_FINE"
    svc.contest_fine(rid, k["renter"], f["id"])
    assert code(svc.contest_fine, rid, k["renter"], f["id"]) == "NOT_CONTESTABLE"


def test_a_contested_fine_whose_invoice_paypal_refuses_has_no_invoice_id(monkeypatch):
    svc = make()
    rid, k, f = _fined(svc)
    monkeypatch.setattr(svc.pp, "create_invoice", lambda *a, **kw: BAD)
    out = svc.contest_fine(rid, k["renter"], f["id"])
    assert out["status"] == "contested_invoiced" and out["invoice_id"] is None


def test_the_daily_close_marks_unlisted_captures_pending_and_skips_the_void_row_without_a_void():
    svc = make()
    rid, k = to_out(svc)
    out = svc.daily_close()
    assert out["transaction_search_status"] == 200
    fee = [x for x in out["rows"] if x["rental"] == rid]
    assert fee and fee[0]["match"] == "pending" and fee[0]["kind"] == "fee"
    assert not [x for x in out["rows"] if x["kind"] == "void"]
    assert out["summary"] == {"match": 0, "pending": len(fee), "mismatch": 0}


def test_a_capture_still_pending_is_read_back_each_time_and_never_cached(monkeypatch):
    svc = make()
    calls = []

    def pending(cid, rid):
        calls.append(cid)
        return Resp(200, {"id": cid, "status": "PENDING"}, "dbg", "capture.get", rid, 1)

    monkeypatch.setattr(svc.pp, "get_capture", pending)
    assert svc._final_status("capture", "C1", "R-1") == "PENDING" and svc._final_status("capture", "C1", "R-1") == "PENDING"
    assert calls == ["C1", "C1"]


def test_the_daily_job_voids_a_returned_rental_near_hold_expiry_and_captures_a_due_fine():
    svc = make()
    old, _ = to_returned(svc)
    r = svc.get(old)
    r["auth_created_at"] = iso(now() - timedelta(days=28))
    svc._save(r)
    fined = make()
    svc2 = fined
    rid, k, f = _fined(svc2)
    row = svc2.db.get_json(f"fine:{f['id']}")
    row["contest_until"] = iso(now() - timedelta(days=1))
    svc2.db.set_json(f"fine:{f['id']}", row)
    svc2.db.zadd("fines:due", 1, f["id"])
    out2 = svc2.cron_daily()
    assert out2["fines"] and not out2["errors"]
    out = svc.cron_daily()
    assert out["expiry_void"] == [old] and svc.get(old)["settlement"]["forced"] is True


def test_a_failing_judge_sweep_or_daily_close_is_reported_not_raised():
    svc = make()

    def boom(*a, **kw):
        raise ServiceError(500, "SWEEP_DOWN", "x")

    svc.judge_void_sweep = boom
    svc.daily_close = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("search down"))
    out = svc.cron_daily()
    kinds = {(e["kind"], e["error"]) for e in out["errors"]}
    assert kinds == {("judge_void", "SWEEP_DOWN"), ("close", "RuntimeError")}


def test_the_judge_sweep_drops_settled_and_vanished_holds_from_the_open_index():
    svc = make()
    rid, k = to_returned(svc)
    svc.release(rid, k["shop"])
    svc.db.zadd("judge:open", 1, rid)
    svc.db.zadd("judge:open", 1, "R-gone")
    assert svc.judge_void_sweep() == []
    assert svc.db.zrange("judge:open") == []


def test_the_judge_path_without_a_pool_or_with_every_wallet_refused_is_an_error():
    assert code(make().mint_judge, "1.1.1.1") == "NO_JUDGE_POOL"
    assert code(make(JUDGE_VAULT_IDS="bad-1,bad-2").mint_judge, "1.1.1.2") == "JUDGE_POOL_FAILED"


def test_a_staged_baseline_is_cloned_into_the_judge_rental_and_stops_at_returned():
    svc = make()
    rid, k = to_returned(svc)
    src = svc.get(rid)
    manifest = {"pickup": src["photos"]["pickup"], "return": src["photos"]["return"], "closeups": [],
                "baseline_marks": [], "source": "test fixture", "walkaround": "w"}
    svc.staged_manifest = lambda: manifest
    svc.s = type(svc.s)(judge_vault_ids=("vault-ok",), app_url="https://jaminan.test", benchmarked_model="x")
    r = svc.mint_judge("2.2.2.2")
    assert r["state"] == "RETURNED" and r["staged"] == {"source": "test fixture", "walkaround": "w"}
    assert len(r["photos"]["return"]) == 8 and r["photos"]["pickup"] == src["photos"]["pickup"]

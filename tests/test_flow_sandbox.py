"""The service end to end on the REAL PayPal sandbox (memory store; scripted model answers, because the
vision accuracy bench runs separately on the staged photo set). Every money step is read back from PayPal."""
import os
import uuid

import pytest

from jaminan.config import Settings
from jaminan.paypal import PayPal
from jaminan.service import Service
from jaminan.store import MemoryStore
from tests.fakes import ScriptedVision, frame_bytes

pytestmark = pytest.mark.sandbox
BENCH = "scripted-test-model"


@pytest.fixture
def svc(local_env, sandbox_vault_id):
    os.environ["JAMINAN_BENCHMARKED_MODEL"] = BENCH
    os.environ["JUDGE_VAULT_IDS"] = f"bad-token-for-failover,{sandbox_vault_id}"
    os.environ.setdefault("APP_URL", "https://jaminan.example")
    try:
        s = Settings()
    finally:
        os.environ.pop("JAMINAN_BENCHMARKED_MODEL")
        os.environ.pop("JUDGE_VAULT_IDS")
    vision = ScriptedVision(model=BENCH, claims={(3, "side_panel", "dent"): {"visible_at_pickup": True}})
    return Service(s, MemoryStore(prefix=f"jaminan:test:{uuid.uuid4().hex[:6]}:"),
                   PayPal(s.paypal_base, s.paypal_client_id, s.paypal_client_secret), vision)


def returned_judge_rental(svc):
    r = svc.mint_judge(f"test-{uuid.uuid4().hex[:6]}")
    assert r["state"] == "OUT" and r["auth_status"] == "PARTIALLY_CAPTURED"
    # the staged set is not in the repo yet: give the cloned rental synthetic frames to exercise the money path
    rid, k = r["id"], r["keys"]
    rr = svc.get(rid)
    for a in range(1, 9):
        rr["photos"]["pickup"][str(a)] = None
    svc.db.set_json(f"rental:{rid}", rr)
    for a in range(1, 9):
        svc.db.set_bytes(f"frame:p{a}", frame_bytes(a))
        svc.db.set_bytes(f"frame:r{a}", frame_bytes(100 + a))
    rr = svc.get(rid)
    rr["photos"]["pickup"] = {str(a): {"sha256": f"p{a}", "angle": a, "low_tiles": []} for a in range(1, 9)}
    rr["photos"]["return"] = {str(a): {"sha256": f"r{a}", "angle": a, "low_tiles": []} for a in range(1, 9)}
    rr["state"] = "RETURNED"
    svc.db.set_json(f"rental:{rid}", rr)
    return rid, k


def test_judge_pool_failover_then_clean_release_reads_back_voided(svc):
    r = svc.mint_judge(f"test-{uuid.uuid4().hex[:6]}")
    calls = svc.calls(r["id"])
    assert [c["http_status"] for c in calls if c["action"] == "order.create.mit.authorize"][0] >= 400  # bad token first
    out = svc.release(r["id"], r["keys"]["shop"])
    assert out["settlement"]["auth_read_back"] == "VOIDED"
    assert svc.pp.get_authorization(out["authorization_id"]).body["status"] == "VOIDED"


def test_accepted_line_is_one_final_capture_and_paypal_refuses_a_second(svc):
    rid, k = returned_judge_rental(svc)
    new = svc.claim(rid, k["shop"], 2, [0.4, 0.3, 0.12, 0.12], "mirror_housing", "crack")["finding"]
    old = svc.claim(rid, k["shop"], 3, [0.45, 0.45, 0.1, 0.1], "side_panel", "dent")["finding"]
    assert (new["disposition"], old["disposition"]) == ("chargeable", "excluded_baseline")
    svc.propose(rid, k["shop"])
    svc.decide_line(rid, k["renter"], new["id"], "accepted")
    r = svc.settle(rid, k["renter"])
    aid = r["authorization_id"]
    assert r["settlement"]["auth_read_back"] == "CAPTURED" and r["settlement"]["capture_cents"] == 1800
    cap = svc.pp.get_capture(r["settle_capture_id"]).body
    assert cap["status"] == "COMPLETED" and cap["amount"]["value"] == "18.00" and cap["final_capture"] is True
    refused = svc.pp.capture(aid, 100, False, f"{rid}-again", "must be refused", action="auth.capture.after_final")
    assert refused.status == 422 and refused.issue == "AUTHORIZATION_ALREADY_CAPTURED"


def test_contested_line_is_invoiced_sent_and_qr_coded_and_the_hold_voided(svc):
    rid, k = returned_judge_rental(svc)
    line = svc.claim(rid, k["shop"], 1, [0.4, 0.4, 0.1, 0.1], "front_fairing", "dent")["finding"]
    svc.propose(rid, k["shop"])
    svc.decide_line(rid, k["renter"], line["id"], "contested")
    r = svc.settle(rid, k["renter"])
    assert r["state"] == "INVOICED" and r["settlement"]["auth_read_back"] == "VOIDED"
    inv = r["invoice"]
    assert inv["id"] and inv["create_status"] in (200, 201)
    got = svc.pp.get_invoice(inv["id"]).body
    assert got["amount"]["value"] == "45.00"
    assert inv["send_status"] in (200, 202) and got["status"] in ("SENT", "UNPAID"), got["status"]
    assert inv["qr_status"] == 200


@pytest.mark.slow
def test_one_real_buyer_approval_authorizes_and_vaults(svc):
    """S1 through the service: the sandbox buyer approves on the PayPal page in a headless browser."""
    if os.environ.get("JAMINAN_SKIP_BROWSER"):
        pytest.skip("browser approval skipped")
    from scripts.sandbox_buyer import approve
    r = svc.create_rental("shop-demo", "veh-01", 1)
    out = svc.approve(r["id"])
    approve(out["approve_url"])
    a = svc.authorize(r["id"])
    assert a["state"] == "APPROVED" and a["vault_id"]
    assert svc.pp.get_authorization(a["authorization_id"]).body["status"] == "CREATED"
    v = svc.pp.void(a["authorization_id"])
    assert v.ok

"""Integration tests against the REAL PayPal sandbox. Each asserts the side effect by reading the
object back from PayPal (R11), not by trusting our own return value."""
import uuid

import pytest

from jaminan.config import Settings
from jaminan.paypal import PayPal, first_authorization, request_id

pytestmark = pytest.mark.sandbox


@pytest.fixture(scope="module")
def pp(local_env):
    calls = []
    s = Settings()
    client = PayPal(s.paypal_base, s.paypal_client_id, s.paypal_client_secret, on_call=calls.append)
    client.calls = calls
    return client


def _hold(pp, vault_id, cents=11500):
    ref = f"T-{uuid.uuid4().hex[:10]}"
    r = pp.create_vault_order(ref, vault_id, cents, "AUTHORIZE", "test hold: fee + deposit")
    assert r.ok, r.body
    auth = first_authorization(r.body)
    assert auth and auth["status"] == "CREATED"
    return ref, auth["id"]


def test_fee_capture_keeps_hold_open_then_final_capture_closes_it(pp, sandbox_vault_id):
    ref, aid = _hold(pp, sandbox_vault_id)
    fee = pp.capture(aid, 1500, False, f"{ref}-fee", "Rental fee")
    assert fee.ok and fee.body["status"] == "COMPLETED"
    assert pp.get_authorization(aid).body["status"] == "PARTIALLY_CAPTURED"

    dmg = pp.capture(aid, 1800, True, f"{ref}-dmg", "Accepted line: mirror housing crack")
    assert dmg.ok and dmg.body["status"] == "COMPLETED"
    assert pp.get_authorization(aid).body["status"] == "CAPTURED"

    again = pp.capture(aid, 100, False, f"{ref}-again", "must be refused", action="auth.capture.after_final")
    assert again.status == 422
    assert again.issue in ("AUTHORIZATION_ALREADY_CAPTURED", "MAX_CAPTURE_COUNT_EXCEEDED")


def test_void_after_fee_capture_releases_the_hold(pp, sandbox_vault_id):
    ref, aid = _hold(pp, sandbox_vault_id)
    assert pp.capture(aid, 1500, False, f"{ref}-fee", "Rental fee").ok
    v = pp.void(aid)
    assert v.status in (200, 204)
    assert pp.get_authorization(aid).body["status"] == "VOIDED"


def test_replayed_capture_is_idempotent(pp, sandbox_vault_id):
    """I4: the same PayPal-Request-Id returns the same capture, never a second one."""
    ref, aid = _hold(pp, sandbox_vault_id)
    a = pp.capture(aid, 1500, False, f"{ref}-fee", "Rental fee")
    b = pp.capture(aid, 1500, False, f"{ref}-fee", "Rental fee")
    assert a.ok and b.ok and a.body["id"] == b.body["id"]
    assert a.request_id == b.request_id == request_id(aid, "auth.capture.partial", 1500)
    pp.void(aid)


def test_every_call_is_logged_with_a_debug_id(pp):
    writes = [c for c in pp.calls if c["method"] == "POST"]
    assert writes and all(c["debug_id"] for c in writes)

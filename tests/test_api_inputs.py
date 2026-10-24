"""Public API edges: malformed input is a 4xx with a reason, never a 500."""
import hashlib

from fastapi.testclient import TestClient

import api.index as api_index
from tests.fakes import frame_bytes
from tests.test_service_flow import make, to_out


def client_for(svc):
    api_index._svc = svc
    return TestClient(api_index.app, raise_server_exceptions=False)


def test_a_malformed_crop_box_is_a_400_and_a_good_one_crops():
    svc = make()
    jpeg = frame_bytes(1)
    sha = hashlib.sha256(jpeg).hexdigest()
    svc.db.set_bytes(f"frame:{sha}", jpeg)
    try:
        c = client_for(svc)
        for bad in ("0.1,0.2", "a,b,c,d", "nan,0.1,0.1,0.1", "0.1,0.1,0.1,inf"):
            r = c.get(f"/api/frames/{sha}", params={"bbox": bad})
            assert r.status_code == 400 and r.json()["error"] == "BAD_BBOX", bad
        ok = c.get(f"/api/frames/{sha}", params={"bbox": "0.4,0.4,0.1,0.1", "scale": 2})
        assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg"
    finally:
        api_index._svc = None


def test_uploads_over_4_mb_are_refused_on_both_photo_and_fine():
    svc = make()
    rid, k = to_out(svc)
    big = b"\xff" * 4_000_001
    try:
        c = client_for(svc)
        h = {"X-Jaminan-Key": k["shop"]}
        p = c.post(f"/api/rentals/{rid}/photos", data={"phase": "return", "angle": "1"}, files={"file": ("f.jpg", big)},
                   headers=h)
        f = c.post(f"/api/rentals/{rid}/fines", data={"ticket_amount_idr": "100000"}, files={"file": ("t.jpg", big)},
                   headers=h)
    finally:
        api_index._svc = None
    assert (p.status_code, f.status_code) == (413, 413)


def test_a_webhook_that_is_not_json_is_a_400():
    svc = make()
    try:
        c = client_for(svc)
        r = c.post("/api/webhooks/paypal", content=b"not json", headers={"Content-Type": "application/json"})
        ok = c.post("/api/webhooks/paypal", json={"id": "WH-1", "event_type": "PAYMENT.AUTHORIZATION.VOIDED",
                                                   "resource": {"id": "A1", "status": "VOIDED"}})
    finally:
        api_index._svc = None
    assert r.status_code == 400 and ok.status_code == 200 and svc.db.lrange_json("webhooks", -1, -1)[0]["id"] == "WH-1"

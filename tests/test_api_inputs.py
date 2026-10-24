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


def test_an_upload_that_is_not_an_image_is_a_422():
    svc = make()
    rid, k = to_out(svc)
    try:
        c = client_for(svc)
        r = c.post(f"/api/rentals/{rid}/photos", data={"phase": "return", "angle": "1"},
                   files={"file": ("f.jpg", b"definitely not a jpeg")}, headers={"X-Jaminan-Key": k["shop"]})
    finally:
        api_index._svc = None
    assert r.status_code == 422 and r.json()["error"] == "NOT_AN_IMAGE"


def test_a_repeated_tap_is_a_409_and_a_bad_body_keeps_the_error_shape():
    svc = make()
    rid, k = to_out(svc)
    for a in range(1, 9):
        svc.add_photo(rid, k["shop"], "return", a, frame_bytes(100 + a))
    try:
        c = client_for(svc)
        h = {"X-Jaminan-Key": k["shop"]}
        first = c.post(f"/api/rentals/{rid}/return/complete", headers=h)
        again = c.post(f"/api/rentals/{rid}/return/complete", headers=h)
        bad = c.post(f"/api/rentals/{rid}/claims", json={"angle": 1}, headers=h)
        odd = c.get(f"/api/rentals/{rid}", headers={"X-Jaminan-Key": "clé".encode("latin-1")})
    finally:
        api_index._svc = None
    assert first.status_code == 200 and again.status_code == 409 and again.json()["error"] == "ILLEGAL_TRANSITION"
    assert bad.status_code == 422 and bad.json()["error"] == "BAD_REQUEST" and "bbox" in bad.json()["message"]
    assert odd.status_code == 403


def test_the_full_judge_path_shares_the_judge_rate_limit_and_photos_name_a_real_angle():
    svc = make()
    try:
        c = client_for(svc)
        codes = [c.post("/api/judge/full").status_code for _ in range(13)]
        rid, k = to_out(svc)
        p = c.post(f"/api/rentals/{rid}/photos", data={"phase": "return", "angle": "9"},
                   files={"file": ("f.jpg", frame_bytes(1))}, headers={"X-Jaminan-Key": k["shop"]})
    finally:
        api_index._svc = None
    assert codes[:12] == [200] * 12 and codes[12] == 429
    assert p.status_code == 422 and p.json()["error"] == "BAD_ANGLE"

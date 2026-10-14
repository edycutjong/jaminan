"""The read-back endpoint behind every "What PayPal says" panel: cached, but never across a state change."""
from fastapi.testclient import TestClient

import api.index as api_index
from tests.test_service_flow import make, to_returned


def test_read_back_after_release_is_never_the_cached_status_from_before_it():
    svc = make()
    rid, k = to_returned(svc)
    api_index._svc = svc
    try:
        client = TestClient(api_index.app)
        before = client.get("/api/integrations/verify", params={"rental": rid}).json()["read_back"]["status"]
        svc.release(rid, k["shop"])
        after = client.get("/api/integrations/verify", params={"rental": rid}).json()["read_back"]["status"]
    finally:
        api_index._svc = None
    assert (before, after) == ("PARTIALLY_CAPTURED", "VOIDED")

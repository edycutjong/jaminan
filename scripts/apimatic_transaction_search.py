"""Transaction Search through PayPal's APIMatic-generated `paypal-server-sdk`, written with the APIMatic Context
Plugin's skills (python-client-initialization: pin Environment.SANDBOX explicitly, flat kwargs; python-calling-
endpoints: search_transactions takes a single options dict, payload on .body).

Question for the daily close: do voids appear in Transaction Search, or must the close re-read each authorization?
Run from the repo root:  pip install paypal-server-sdk && python scripts/apimatic_transaction_search.py
(not part of the app: the product keeps its hand-written REST client in jaminan/paypal.py)."""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from jaminan.config import load_local_env  # noqa: E402

load_local_env()
from paypalserversdk.configuration import Environment  # noqa: E402
from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials  # noqa: E402
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient  # noqa: E402

client = PaypalServersdkClient(
    environment=Environment.SANDBOX,  # plugin warning: never rely on the default environment
    client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
        o_auth_client_id=os.environ["PAYPAL_CLIENT_ID"], o_auth_client_secret=os.environ["PAYPAL_CLIENT_SECRET"]),
    timeout=30)
end = datetime.datetime.now(datetime.timezone.utc)
start = end - datetime.timedelta(days=2)
fmt = "%Y-%m-%dT%H:%M:%S-0000"
try:
    res = client.transaction_search.search_transactions({
        "start_date": start.strftime(fmt), "end_date": end.strftime(fmt),
        "fields": "transaction_info", "page_size": 500})
except Exception as exc:  # the SDK raises on 4xx; print what PayPal said
    print(json.dumps({"error": type(exc).__name__, "http_status": getattr(exc, "response_code", None),
                      "message": str(exc)[:300]}, indent=1))
    sys.exit(1)
rows = [t.transaction_info for t in (res.body.transaction_details or [])]
print(json.dumps({"http_status": res.status_code, "debug_id": res.headers.get("Paypal-Debug-Id"), "listed": len(rows),
                  "event_codes": sorted({r.transaction_event_code for r in rows}),
                  "statuses": sorted({r.transaction_status for r in rows}),
                  "at": end.isoformat(timespec="seconds")}, indent=1))

# APIMatic Context Plugin: what was used, and what it showed

Jaminan's PayPal client (`jaminan/paypal.py`) is hand-written REST. The APIMatic Context Plugin was used for one thing: writing a call to PayPal's Transaction Search through PayPal's APIMatic-generated `paypal-server-sdk` (2.4.0), to find out whether the daily close could reconcile from Transaction Search. No product code depends on it.

1. **Install** (2026-10-14): `npx context-plugins install https://github.com/paypaldev/server-sdk-context-plugin-preview`. No login or key was needed. The plugin is a set of per-language skills for `paypal-server-sdk`; the Python ones were used.
2. **What the SDK covers.** Controllers for orders, payments, vault, transaction search, subscriptions and OAuth ([`evidence/apimatic-transaction-search.txt`](../evidence/apimatic-transaction-search.txt), last line). It has no Invoicing v2 or verify-webhook-signature controller, so those stay in the hand-written client.
3. **The call** ([`scripts/apimatic_transaction_search.py`](../scripts/apimatic_transaction_search.py)). The plugin's `python-client-initialization` skill supplied the pinned `Environment.SANDBOX` (the default environment is a trap) and the flat constructor arguments; `python-calling-endpoints` supplied the single options dict for `search_transactions` and the payload on `.body`.
4. **The result.** The request authenticated, and PayPal answered **403 `NOT_AUTHORIZED`** because Transaction Search is not enabled on this sandbox app. The output of a run is in [`evidence/apimatic-transaction-search.txt`](../evidence/apimatic-transaction-search.txt) (debug id `ca4a910fb192c`).

Until the permission is enabled on the app, the daily close reconciles each capture and void by reading the object back from PayPal (`GET /v2/payments/captures/{id}`, `GET /v2/payments/authorizations/{id}`); see `evidence/README.md`.

```bash
pip install paypal-server-sdk
python scripts/apimatic_transaction_search.py
```

This is the full extent of the plugin's use in this project.

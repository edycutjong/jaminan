# APIMatic Context Plugin: what was used, and what it showed

Jaminan's PayPal client (`jaminan/paypal.py`) is hand-written REST. The APIMatic Context Plugin was used for one thing: writing a call to PayPal's Transaction Search through PayPal's APIMatic-generated `paypal-server-sdk` (2.4.0), to find out whether the daily close could reconcile from Transaction Search. No product code depends on it.

| Date (2026-10-14, WIB) | Step | Result |
|---|---|---|
| 12:35 | `npx context-plugins install https://github.com/paypaldev/server-sdk-context-plugin-preview` | Installed into Claude Code (user scope); no login or key needed. The installer also installed it into Cursor, VS Code and Codex. The plugin is 6 language skill sets for `paypal-server-sdk`; we used the Python ones. |
| 12:45 | Read what the SDK covers | Controllers for orders, payments (including `reauthorize_payment` and `void_payment`), vault (`delete_payment_token`), transaction search, subscriptions and OAuth. It does **not** cover Invoicing v2 or verify-webhook-signature, so those stay in the hand-written client. |
| 12:50 | `scripts/apimatic_transaction_search.py` | The `python-client-initialization` skill supplied the pinned `Environment.SANDBOX` (the default environment is a trap) and the flat constructor arguments; `python-calling-endpoints` supplied the single options dict for `search_transactions` and the payload on `.body`. The request authenticated on the first try. PayPal answered **403 `NOT_AUTHORIZED`** (debug id `f4098864d0ef0`), because Transaction Search is not enabled on this sandbox app. |

Re-running the script today gives the same 403 (debug id `f6760554dfa8e`). Until the permission is enabled on the app, the daily close reconciles each capture and void by reading the object back from PayPal (`GET /v2/payments/captures/{id}`, `GET /v2/payments/authorizations/{id}`); see `evidence/README.md`.

```bash
pip install paypal-server-sdk
python scripts/apimatic_transaction_search.py
```

This is the full extent of the plugin's use in this project.

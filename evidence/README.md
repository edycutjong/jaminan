# Evidence

Every test, PayPal and coverage number on the landing page, the pitch deck and the README comes from a file in this
folder or from the test files it names. Recorded 2026-10-14 (UTC times inside each file), except
`paypal-reauthorize.jsonl` (2026-10-23, local WIB times, UTC+7) and `test-run.txt`, `coverage.txt` and `e2e-live.txt`
(re-recorded 2026-10-24).

| File | What it is | Reproduce |
|---|---|---|
| [`paypal-sandbox-run.json`](paypal-sandbox-run.json) | Three settlements on the real PayPal sandbox, call by call: method, path, HTTP status, the status PayPal returned, amount, `final_capture`, PayPal debug id, milliseconds | `.venv/bin/python scripts/record_paypal_evidence.py` |
| [`test-run.txt`](test-run.txt) | The full suite, one line per test: **235 passed** (226 offline, 8 against the real PayPal sandbox, 1 against the live Qwen API) | `.venv/bin/python -m pytest -v` (needs sandbox + Qwen credentials) |
| [`coverage.txt`](coverage.txt) | Offline suite with coverage: **100%** of `jaminan/`, line and branch (1,675 statements, 492 branches), plus the Vitest run of the web `lib/` (31 tests, 100%) | `.venv/bin/python -m pytest -m "not sandbox and not live_model and not slow" --cov=jaminan --cov-branch` |
| [`e2e-live.txt`](e2e-live.txt) | The live app driven as two phones at 375 px on https://jaminan.edycu.dev/app on 2026-10-24 (rental R-1024-3A9FC469; the pointed claim reached `qwen3-vl-plus` and ended `comparison_unavailable`, as no model is pinned): **18/18** acceptance checks. The first run, 2026-10-14 (R-1014-2E81996C, the landing's counter screenshot), is [`e2e-live-2026-10-14.txt`](e2e-live-2026-10-14.txt) | `python scripts/e2e_live.py https://jaminan.edycu.dev/app --shots /tmp/shots` |
| [`paypal-reauthorize.jsonl`](paypal-reauthorize.jsonl) | `POST /v2/payments/authorizations/{id}/reauthorize` (the endpoint `PayPal.reauthorize` calls) on 2026-10-23, day 9 of two 2026-10-14 sandbox holds: **201** on a plain hold (`94D57335A25884833`), **201** on a hold whose fee was already captured (`1CE70904NP210710M`), then a second reauthorize on the first hold refused **422 `REAUTHORIZATION_TOO_SOON`** ("only allowed once from Day 4 to Day 29"). PayPal debug ids included | needs a sandbox hold between Day 4 and Day 29; works once per hold |
| [`video-run.json`](video-run.json) | The live sandbox rentals the demo video shows (take of 2026-10-14, 20:16–21:28 UTC): the renter approval, the judge rental R-JUDGE-16 (every call, the read-backs printed on the page, its webhooks, and the verify page's webhook table as captured), and the recorded pytest run on the terminal plate | not reproducible from this repo alone: a new take mints new sandbox objects |
| [`apimatic-transaction-search.txt`](apimatic-transaction-search.txt) | The output of `scripts/apimatic_transaction_search.py` (PayPal's generated SDK): 403 `NOT_AUTHORIZED` on Transaction Search, and the SDK's controller list; see `docs/APIMATIC.md` | `pip install paypal-server-sdk && python scripts/apimatic_transaction_search.py` |
| [`mcp/`](mcp/README.md) | The MCP rental tool: `tools/list` returns 4 tools over stdio. Claude Code and Codex each booked through it on 2026-10-24, and the sandbox renter approved in PayPal. Each agent then read back the authorization: `8S39497205940830X` for USD 130.00 and `4V462197H4984864E` for USD 145.00. The agent's token gets 403 on 8 live write routes | `scripts/mcp_tools_list.py`, `scripts/mcp_renter_approves.py`, see the README there |
| [`generated-pair/`](generated-pair/README.md) | **AI-generated test images (not photographs)**: a generated pickup/return pair and the vision model's recorded answers to two pointed claims through the app's claim path, 3 calls each (`qwen3-vl-plus`, request ids inside). It read both claims wrong; nothing was charged (no model is benchmarked). Not a benchmark | `.venv/bin/python scripts/generated_pair.py` (needs a Qwen key) |

## The three recorded settlements (`paypal-sandbox-run.json`)

Each rental is a merchant-initiated `AUTHORIZE` of **$115.00** (fee $15.00 + deposit $100.00) on a saved sandbox
wallet, then the fee captured from the hold with `final_capture=false` (PayPal reads back `PARTIALLY_CAPTURED`).

| Run | Rental | What happens | PayPal's read-back |
|---|---|---|---|
| `accepted` | R-JUDGE-9001 | the renter accepts the new mirror crack: ONE capture of **$18.00** with `final_capture=true`; then a second capture is attempted | `CAPTURED`, **$82.00** released; second capture refused **422 `AUTHORIZATION_ALREADY_CAPTURED`** |
| `clean` | R-JUDGE-9002 | no new damage: the shop's one tap voids the hold | `VOIDED`, $100.00 released |
| `contested` | R-JUDGE-9003 | the renter contests the same crack: an itemized invoice at the tariff price ($18.00) is created, sent and QR-coded | `VOIDED`, invoice sent |

**What is scripted:** the claim answers. The vision benchmark on the staged scooter photo set has not run, so the
recording uses `tests/fakes.ScriptedVision` (model id `scripted-test-model`) to answer "is this mark new since
pickup?". Everything PayPal did is real. The R-JUDGE-90xx ids belong to the recording's in-memory store, not to the
live app.

## PayPal REST endpoints in `jaminan/paypal.py` (19)

Orders v2: create (buyer approval and merchant-initiated on `vault_id`), get, authorize, track ·
Payments v2: authorization capture, void, reauthorize, get authorization, get capture ·
Vault v3: get payment token, delete payment token ·
Invoicing v2: create, send, generate QR code, get ·
Reporting: transaction search ·
Notifications: verify webhook signature, list webhooks, create webhook.

Transaction search returns 403 `NOT_AUTHORIZED` on this sandbox app until the feature is enabled on the developer
dashboard; the daily close reconciles by per-object read-back meanwhile.

## Recorded note: the card path
Advanced Card Processing (`AUTHORIZE` with a card and vault) was tried on this sandbox app on 2026-10-14 and PayPal answered
`422 UNPROCESSABLE_ENTITY` without a stated reason (we believe advanced cards are not enabled for this Indonesia-region sandbox merchant). Jaminan is therefore
wallet-only; nothing in the product depends on the card path.

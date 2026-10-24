# Demo guide

Everything here runs on the **PayPal sandbox**. No real money moves. The app is live at <https://jaminan.edycu.dev/app>; no install is needed.

## 1. Two minutes: the judge route

Open <https://jaminan.edycu.dev/app/judge> and tap **Start a judge rental**. Each tap mints a fresh rental (`R-JUDGE-<n>`) as a merchant-initiated `AUTHORIZE` of **$115.00** (fee $15.00 + deposit $100.00) on a saved sandbox wallet, captures the $15.00 fee with `final_capture=false`, writes the handover tracking, and opens a "Hold is live" screen with a read-back panel. No login is needed for this path. (The other button, "Full path", sends you through the real PayPal approval page; the sandbox buyer login is printed on the page.)

| Step | What you see | What PayPal did |
|---|---|---|
| Rental opens | The stub shows the hold; the panel on the right lists the authorization, fee capture and handover ids | `POST /v2/checkout/orders` (`intent=AUTHORIZE`), `…/authorizations/{id}/capture` (`final_capture=false`), `…/orders/{id}/track` |
| Tap **Release the hold (clean return)** | The green RELEASED stamp lands over the hold | `POST …/authorizations/{id}/void`, then a read-back `GET`; the screen shows the status PayPal returned (`VOIDED`) |
| Click **Full call log with debug ids** (`/integrations/verify?rental=<id>`) | Every PayPal call for that rental: action, object id, HTTP status, PayPal debug id, milliseconds; plus a live read-back line with the authorization status PayPal returns now | The same calls, read back live. The bare `/integrations/verify` lists the most recent calls across all rentals and has no read-back line |

The settle screen only stamps after PayPal's read-back, not after our own call returns.

**What the live route cannot do yet.** The staged scooter photo set is not in this deploy and no vision model is pinned as benchmarked, so on `/judge` you can release the hold but cannot tap a claim. On the ordinary shop flow a pointed claim ends `comparison_unavailable — nothing charged from the hold`. That is deliberate: only a benchmarked model can produce a chargeable line. The priced path is shown below as a recording and exercised by the test suite.

### Below the button: AI-generated test images (not photographs), recorded model answers

The same page shows a pickup/return pair of **AI-generated test images (not photographs)**: a white scooter made by
`qwen-image-2.0`, and a `wan2.6-image` edit of it with both mirrors removed ([`GENERATION.json`](evidence/generated-pair/GENERATION.json)).
The builder pointed two claims, and a script running the same crop, model-call and decision steps as the app's claim path asked `qwen3-vl-plus` about each three times
([`evidence/generated-pair/`](evidence/generated-pair/README.md), request ids inside). The answers on screen are those
recorded calls, not live ones:

| Claim | True answer | Model read (all 3 calls) | App answer |
|---|---|---|---|
| C1 `front_fairing` / `dent` on the grey scuff | old: in the pickup image too | new since pickup (wrong) | comparison unavailable — nothing charged from the hold |
| C2 `mirror` / `missing_part` on the mirror mounts | new: both mirrors gone | no missing mirror; a smudge elsewhere (wrong) | comparison unavailable — nothing charged from the hold |

Nothing is charged because no model is benchmarked. Had this model been pinned without the bench, C1 would have been
priced at the tariff's dent price, $45.00, for a mark that was there at pickup. This is not a benchmark and not real-world evidence.

## 2. The priced path, recorded on the sandbox

[`evidence/paypal-sandbox-run.json`](evidence/paypal-sandbox-run.json) holds three settlements recorded against the real PayPal sandbox on 2026-10-14 (`scripts/record_paypal_evidence.py`). The claim answers in these runs are **scripted** (`scripted-test-model`), because the vision benchmark has not run; every PayPal call and every status is real.

| Run | Rental | Authorization | What happened | PayPal read-back |
|---|---|---|---|---|
| `accepted` | R-JUDGE-9001 | `59Y22025SE889191E` | Fee captured $15.00 (`5NS03668PC712303K`, `PARTIALLY_CAPTURED`). Renter accepts the mirror-housing crack: one capture of **$18.00** with `final_capture=true` (`1DK41086KS913835V`). A second capture attempt is refused. | `CAPTURED`; **$82.00** released; second capture **HTTP 422 `AUTHORIZATION_ALREADY_CAPTURED`** (debug `f5799404eea63`) |
| `clean` | R-JUDGE-9002 | `6PV888804V785821A` | No new damage: the shop's one tap voids the hold | `VOIDED`; $100.00 released |
| `contested` | R-JUDGE-9003 | `3EP89225J0560011A` | The renter contests the crack: hold voided, then an itemized $18.00 invoice created, sent and QR-coded (`INV2-EP2Z-3UZM-4A88-7E4W`) | `VOIDED`; invoice sent |

The side-panel dent in the `accepted` run is the "already there" case: it was visible in the pickup baseline, so the rules mark it `excluded_baseline` and it carries no price.

## 3. Reproduce

```bash
# offline suite (230 tests, no credentials)
.venv/bin/python -m pytest -m "not sandbox and not live_model and not slow" --cov=jaminan --cov-branch

# the claim-decision sweep (23,040 combinations) and the settle property test
.venv/bin/python -m pytest tests/test_invariants.py -v

# everything, including 8 real-sandbox tests and 1 live Qwen schema check (needs credentials)
.venv/bin/python -m pytest -v

# record three fresh sandbox settlements (new ids, same statuses)
.venv/bin/python scripts/record_paypal_evidence.py

# drive the live app as two phones at 375 px
python scripts/e2e_live.py https://jaminan.edycu.dev/app --shots /tmp/jaminan-e2e
```

| Number | Where it comes from |
|---|---|
| 239 tests (230 offline, 8 real-sandbox, 1 live Qwen) | [`evidence/test-run.txt`](evidence/test-run.txt) |
| 100% offline line and branch coverage of `jaminan/` | [`evidence/coverage.txt`](evidence/coverage.txt) |
| 18/18 live acceptance checks at 375 px (2026-10-24) | [`evidence/e2e-live.txt`](evidence/e2e-live.txt) |
| 23,040-case claim sweep | [`tests/test_invariants.py`](tests/test_invariants.py) |
| 19 PayPal REST endpoints in the hand-written client | [`evidence/README.md`](evidence/README.md), [`jaminan/paypal.py`](jaminan/paypal.py) |

## 4. An agent books, the renter approves in PayPal

A booking agent sees four MCP tools: `list_vehicles`, `quote_rental`, `start_rental` and `get_rental`
([`jaminan/mcp_server.py`](jaminan/mcp_server.py)). On 2026-10-24 Claude Code booked R-1024-FA0400AA and Codex
booked R-1024-B54EE295. Each agent got back a PayPal `approve_url`. The sandbox renter opened it and approved (a script logged in as the sandbox buyer), and a
new session of each agent called `get_rental`. PayPal reported authorization `8S39497205940830X` (`CREATED`, USD
130.00) and `4V462197H4984864E` (`CREATED`, USD 145.00). An agent cannot approve, answer a damage line, capture, void
or refund: no tool does it, and the agent never holds a key to the rental it booked that would. Transcripts and the live 403s are in
[`evidence/mcp/`](evidence/mcp/README.md). To read one back yourself:

```bash
curl -s "https://jaminan.edycu.dev/api/agent/rentals/R-1024-FA0400AA?t=vG8cd6f18tPt"
```

The `paypal` part is PayPal's answer at the time you ask (cached 10 s). This sandbox hold was never picked up, so
from its expiry on 2026-11-22 PayPal's answer is `EXPIRED`, not the `CREATED` recorded above. Reads are limited to
120 a rental an hour.

## 5. Not shown, on purpose

- **Vision accuracy.** There is no accuracy number anywhere in this repository because the benchmark on the staged scooter photo set has not run. The model has been shown only on AI-generated test images (not photographs) so far (§1).
- **Reauthorize inside a rental.** PayPal allows it once, Day 4 to Day 29. The call itself is recorded on the sandbox ([`evidence/paypal-reauthorize.jsonl`](evidence/paypal-reauthorize.jsonl): 201 on two holds, 422 on a second attempt); no rental in the app has reached day 4, so only the sweep's day-4 trigger rule and its refusal fallback are unit-tested, as is `cron_daily()` (the cron route and Vercel's schedule have not fired on a real rental).
- **Live money.** Sandbox only.

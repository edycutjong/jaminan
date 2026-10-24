<div align="center">
  <img src="docs/assets/icon-animated.svg" alt="Jaminan icon — a red stamp on the one accepted line, a green stamp releasing the rest of the hold" width="144">
  <h1>Jaminan 🛵</h1>
  <p><em>A PayPal hold that replaces the passport at the scooter-rental counter. The shop points, the shared baseline answers, and PayPal moves only the money the renter accepted.</em></p>
  <img src="docs/assets/readme-hero-animated.svg" alt="Jaminan — a PayPal hold instead of your passport. One red stamp for the cracked mirror; one green stamp releases the rest of the hold." width="100%">

  <br/>

  [![Live Demo](https://img.shields.io/badge/🚀_Live-Demo-06b6d4?style=for-the-badge)](https://jaminan.edycu.dev/app)
  [![Judge Path](https://img.shields.io/badge/⚖️_Judge-Path-f59e0b?style=for-the-badge)](https://jaminan.edycu.dev/app/judge)
  [![Landing Page](https://img.shields.io/badge/🧾_Landing-Page-1D7A4A?style=for-the-badge)](https://jaminan.edycu.dev)
  [![Pitch Deck](https://img.shields.io/badge/🗂️_Pitch-Deck-3346A6?style=for-the-badge)](https://jaminan.edycu.dev/pitch/)
  [![Built for PayPal AI Hackathon](https://img.shields.io/badge/Devpost-PayPal_AI_Hackathon-8b5cf6?style=for-the-badge)](https://paypalaihackathon.devpost.com/)

  <br/>

  ![Next.js](https://img.shields.io/badge/Next.js_16-black?style=flat&logo=next.js)
  ![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat&logo=typescript&logoColor=white)
  ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
  ![PayPal](https://img.shields.io/badge/PayPal_Sandbox-003087?style=flat&logo=paypal&logoColor=white)
  ![Upstash](https://img.shields.io/badge/Upstash_Redis-00E9A3?style=flat&logo=upstash&logoColor=black)
  [![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
  [![CI/CD](https://img.shields.io/github/actions/workflow/status/edycutjong/jaminan/ci.yml?branch=main&label=CI%2FCD)](https://github.com/edycutjong/jaminan/actions/workflows/ci.yml)
  [![Release](https://img.shields.io/github/v/release/edycutjong/jaminan?color=1D7A4A)](https://github.com/edycutjong/jaminan/releases)

</div>

---

## 💡 The Problem & Solution

### The Problem

In Bali and Jakarta the deposit on a rented scooter is often your passport (or a local's KTP). At return the shop points at a dent, the renter says it was already there, and whoever holds the document wins the argument. Neither side has evidence they both saw, and the "deposit" is a document, not money either side can trust.

### The Solution

Jaminan replaces the passport with a PayPal authorization and replaces the argument with a shared walkaround.

**What runs today, on the PayPal sandbox:** at [`/app/judge`](https://jaminan.edycu.dev/app/judge) one tap authorizes $115.00 on a saved sandbox wallet, captures the $15.00 fee, writes the handover tracking, and releases the hold on a second tap, each stamp waiting for PayPal's read-back. No vision model is pinned as benchmarked yet, so a live rental cannot price a damage line. The priced path is a recorded sandbox run with scripted claim answers ([`evidence/paypal-sandbox-run.json`](evidence/paypal-sandbox-run.json): one $18.00 capture with `final_capture=true`, the other $82.00 released, a second capture refused with 422) and is exercised in the unit and sandbox tests.

1. The renter scans the shop QR and gives **one PayPal approval** that authorizes the fee plus the deposit and saves the wallet for later fines. The fee is captured when both sides confirm the baseline at pickup; the deposit stays held.
2. A guided 8-angle walkaround records the scooter at pickup. Renter and shop confirm the baseline together.
3. At return **the owner points, the shared baseline answers.** The shop taps a mark and picks its `(part, damage_class)` from the published tariff. The model only answers what the pickup photos show; it never sets a price.
4. Code decides: no mark at return, visible at pickup, or not comparable at pickup all mean **cannot be charged**, and a mark that doesn't look like the kind the shop named can't be paid from the hold. Only clearly new damage becomes a priced line.
5. **The hold only pays lines the renter accepted.** Accepted lines become one capture with `final_capture=true`. A clean return voids the hold. A contested line goes out as an itemized PayPal invoice at its tariff price.

**On AI-generated test images (not photographs):** the same crop, model-call and decision steps as the app's claim path, run from a script (one angle, no rental, no close-ups), asked `qwen3-vl-plus` about two pointed claims on a generated pickup/return pair, three times each, and recorded every answer. It read both wrong. It called the old scuff new: the tariff has no scuff line on the fairing, so the shop named a dent, an over-claim. At the mirror mounts it found no missing mirror, only a smudge elsewhere. No rental or payment was involved, and no line could be priced because no model is benchmarked. C1's error, a false "new" on an old mark, is the one the benchmark has to rule out before any model is pinned. Not a benchmark: [`evidence/generated-pair/`](evidence/generated-pair/README.md).

> **What the shared baseline can't show, nobody can charge.**

## 🏗️ Architecture & Tech Stack

![Jaminan architecture](docs/architecture.png)

<details><summary>Mermaid source</summary>

```mermaid
flowchart LR
  R[Renter phone PWA] --> API
  S[Shop phone PWA] --> API
  subgraph API[FastAPI on Vercel Python functions /api/*]
    G[Frame gate: blur + glare] --> V[Vision: pointed claims]
    V --> F[Deterministic filter + tariff]
    F --> L[State machine + ledger]
    L --> PC[paypal.py REST client]
  end
  V --> Q[Qwen on DashScope]
  PC --> PP[(PayPal sandbox)]
  PP -- webhooks --> API
  L --> DB[(Upstash Redis jaminan:*)]
```

</details>

| Layer | Technology |
|---|---|
| UI | Next.js 16 PWA (App Router), React 19, TypeScript. Bahasa on shop screens, English on renter screens |
| API | Python 3, FastAPI, httpx, Pydantic, deployed as Vercel Python functions |
| Frame gate | numpy + Pillow: Laplacian-variance blur and clipped-highlight glare checks, no model call to reject a bad frame |
| Vision | Qwen via DashScope (OpenAI-compatible, image input, JSON-schema answer) |
| Storage | Upstash Redis, one JSON document per rental, keys prefixed `jaminan:` |
| Jobs | One Vercel Cron entry `/api/cron/daily` (reauth sweep, expiry guard, daily close) |

## 🏆 PayPal Integration

PayPal is the engine, not a decoration: the deposit **is** an authorization, and its whole lifecycle is the product. The REST client is hand-written in [`jaminan/paypal.py`](jaminan/paypal.py).

```
approve (Orders v2 AUTHORIZE + vault consent)
   → capture fee (final_capture=false)  → tracking on the fee capture
   → claims → renter accepts lines
   → { capture accepted lines (final_capture=true) | void }
   → [reauthorize on day 4 for rentals over 3 days]
   → [invoice: contested lines / damage above the hold]
   → [later fine: merchant-initiated capture on the vaulted wallet]
```

| PayPal surface | Used for |
|---|---|
| Orders v2 `AUTHORIZE` with `store_in_vault` | one approval: fee + deposit hold + saved wallet |
| Payments v2 capture (`final_capture` false/true) | fee now, accepted damage lines at settle |
| Payments v2 void | clean return releases the hold |
| Payments v2 reauthorize | re-secures long rentals (Day 4 to Day 29 window) |
| Vault v3 + merchant-initiated charges | later fines on the saved wallet |
| Shipment tracking | handover record on the fee capture; the tracking number carries the first 8 hex characters of the baseline SHA-256 |
| Invoicing v2 | contested lines and damage above the hold, with an evidence-pack link |
| Webhooks v1 and `GET /api/integrations/verify` | events checked with PayPal's verify-webhook-signature call when a webhook id is configured and stored with their verified/failed flag; live read-back of PayPal state |

The APIMatic Context Plugin was used once, to write a Transaction Search call through PayPal's generated SDK ([`docs/APIMATIC.md`](docs/APIMATIC.md)): the request authenticated and PayPal answered 403 `NOT_AUTHORIZED`, because the sandbox app lacks permission for Transaction Search (we believe the feature is not enabled). The client itself is hand-written. The settle screen shows the status read back from PayPal after the call. Real-sandbox tests in [`tests/`](tests) cover authorize, vault, capture, void and invoice; tracking, webhooks and fine capture are covered by offline tests. Outside the tests, tracking runs in the recorded sandbox runs and on every `/app/judge` rental, and incoming webhooks are checked with PayPal's signature call and listed with the result on [`/app/integrations/verify`](https://jaminan.edycu.dev/app/integrations/verify); the fine capture has no sandbox run.

### How this differs

| Existing approach | What it does | What it does not do |
|---|---|---|
| AI fleet-inspection products (e.g. [Monk](https://monk.ai), [Ravin](https://ravin.ai), [ProovStation](https://www.proovstation.com)) | Detect damage on vehicle photos | Their sites do not describe a payment hold, capture or release, as far as we found |
| Turo-style photo check-in | Both sides photograph the car on a marketplace | Tie the photos to an authorization that only accepted lines can capture, as far as we found |
| A phone video before you ride | The renter's own record | Carry a co-signature, or get the passport back |

## 🤖 For booking agents (MCP)

[`jaminan/mcp_server.py`](jaminan/mcp_server.py) is a stdio MCP server that lets an agent book a scooter for a person. The agent can look up vehicles, get a price and ask for a booking. Only the renter can pay. The server calls the same service as the app through the live API (`/api/shops/{id}` and `/api/agent/*`). It needs `mcp` and `httpx`, and no secrets. It runs on the PayPal sandbox.

| Tool | What it does |
|---|---|
| `list_vehicles(shop_id)` | Lists the shop's scooters, each with its daily fee and refundable deposit |
| `quote_rental(vehicle_id, days)` | Returns the fee and deposit, which together make the PayPal hold, plus the tariff version and its SHA-256. The counter uses the same `Service.quote()` |
| `start_rental(vehicle_id, days, renter_email)` | Creates the rental and returns a PayPal `approve_url` for the renter. The rental stays DRAFT, with no hold, until the renter approves |
| `get_rental(rental_id)` | Read-only. Returns the rental's state and PayPal's own record of it: the order before approval, the authorization after |

**What an agent cannot do:** approve the hold, accept or contest a damage line, capture, void or refund. None of these is a tool. The agent routes also never return the shop or renter key that those actions need. The renter's key reaches the renter only through PayPal's return redirect, after they log in and approve. PayPal's cancel link, which its login page shows to anyone holding the approval link, carries no key. `renter_email` only pre-fills the PayPal login, and it approves nothing. Bookings are limited to 12 per IP address per hour and 300 per day in all. The judge route has the same limits, counted separately. Bad input gets a one-line error, never a stack trace. All of this holds for any renter's PayPal account. The one deliberate exception is the sandbox `/judge` route, which holds the project's own pool wallet with no approval so that a judge can try the flow in one tap.

```bash
# from the repo root, after the install below
claude mcp add jaminan -e PYTHONPATH="$PWD" -- "$PWD/.venv/bin/python" -m jaminan.mcp_server          # Claude Code
codex mcp add jaminan --env PYTHONPATH="$PWD" -- "$PWD/.venv/bin/python" -m jaminan.mcp_server       # Codex
npx @modelcontextprotocol/inspector --cli -e PYTHONPATH="$PWD" "$PWD/.venv/bin/python" -m jaminan.mcp_server --method tools/list   # MCP Inspector
```

Recorded on 2026-10-24: Claude Code and Codex each booked through `quote_rental → start_rental → get_rental`. The sandbox renter approved in PayPal (a script logged in as the sandbox buyer: `scripts/mcp_renter_approves.py`), and each agent then read back the authorization in a new session: `CREATED`, for USD 130.00 and USD 145.00. Codex's approval policy blocked `start_rental` until the operator approved that one tool. `list_vehicles` and `quote_rental`, which are annotated read-only, ran without approval. Offline, all 18 write routes under `/api/rentals/{id}` refuse the agent's token. Live, it gets 403 on the 8 money and answer routes. Transcripts and PayPal ids: [`evidence/mcp/`](evidence/mcp/README.md).

## 📊 Engineering Rigor

| Metric | Value |
|---|---|
| Tests collected | 235 (`pytest`): 226 offline unit, contract and invariant tests, 8 against the real PayPal sandbox (including `CAPTURED` and second-capture `422` read-backs), 1 live Qwen schema check; plus 31 Vitest unit tests for the web `lib/` |
| Claim-decision sweep | `decide_claim` run over 23,040 combinations of the five yes/no answers, serving model (pinned, other, none), confidence, a confirmed baseline mark, a low-comparability tile, three parts and five damage classes: every chargeable result satisfies every "new since pickup" condition and carries a tariff price ([`tests/test_invariants.py`](tests/test_invariants.py)) |
| Settle property test | up to 3,000 generated settlements (Hypothesis): the hold pays exactly the accepted chargeable lines at their tariff price, blocks exactly when a line is mispriced, or unanswered and the settle is not forced; invoices only contested lines plus any accepted amount above the deposit; and never captures more than the authorization |
| Offline coverage | 100% of `jaminan/`, line and branch (`pytest --cov --cov-branch`, 1,675 statements, 492 branches), enforced in CI with `--cov-fail-under=100`; 100% of the web `lib/` under Vitest (`npm run test:unit`). Two `# pragma: no cover`: a defensive re-check in `rules.settle_plan` (`rules.py:186`) that the line list makes unreachable, and the abstract `Store._cmd` stub (`store.py:18`) |
| CI | A six-stage GitHub Actions pipeline ([`ci.yml`](.github/workflows/ci.yml)): 1 Quality (ruff, mypy, offline tests with a 100% coverage gate; eslint, `tsc`, Vitest `lib/` tests with a 100% gate) and 2 Security (gitleaks over full history, pip-audit, npm audit, licence check) run in parallel, then 3 Build (`next build`, API boot smoke), 4 E2E (Playwright, no secrets), 5 Performance (Lighthouse CI on `/` and `/pitch`, every category ≥ 0.9, a11y ≥ 0.95) and 6 Deploy gate (every stage green; Vercel deploys only after it). Also gitleaks as its own workflow; CodeQL (Python and TypeScript); GitHub secret scanning with push protection; Dependabot monthly, grouped, no major bumps |
| Live acceptance script | `scripts/e2e_live.py` (375 px viewport) |
| Evidence pack | [`evidence/`](evidence): three recorded PayPal sandbox settlements call by call (`scripts/record_paypal_evidence.py`), the full test run, offline coverage and the live e2e log |
| Vision accuracy | **Not yet measured.** Benchmark on a real-photo scooter set is pending; the model has been shown only on AI-generated test images (not photographs) so far ([recorded answers](evidence/generated-pair/README.md)) |

### Honest limits (7)

1. **Sandbox only.** Nothing here has moved live money; live vault and merchant-initiated eligibility are unverified.
2. **One merchant.** The demo uses a single sandbox merchant; a production path needs one onboarded merchant per shop.
3. **Wallet path only.** The card-path authorize answered 422 on 2026-10-14 without a stated reason (PayPal's response gave none; we believe advanced card processing is not enabled for this Indonesia-region sandbox merchant), so cards are out of scope.
4. **Non-return is out of scope.** Jaminan covers damage and fines, not a scooter that never comes back.
5. **No vision accuracy claim yet.** Until the benchmark runs, no finding from a non-benchmarked model is chargeable.
6. **Reauthorize is proven on the sandbox, not yet through the rental flow.** On 2026-10-23 (day 9) PayPal accepted `reauthorize` on a plain hold and on a hold that already had its fee captured (201 both), and refused a second one on the same hold (422 `REAUTHORIZATION_TOO_SOON`, "only allowed once"): [`evidence/paypal-reauthorize.jsonl`](evidence/paypal-reauthorize.jsonl). The sweep's day-4 trigger rule and its refusal fallback (re-authorize on the vaulted wallet, then void the old hold) are unit-tested, including through `cron_daily()`; the `/api/cron/daily` route and Vercel's schedule have not run on a rental, and no rental has yet reached day 4 through the app.
7. **The model has been shown only on AI-generated test images (not photographs) so far.** Its recorded answers on that pair ([`evidence/generated-pair/`](evidence/generated-pair/README.md)) are not a benchmark and say nothing about real photos.
8. **An agent booking stops at the hold.** The shop phone opens only the rentals it created, because it holds their key, and no shop login exists yet. So nobody can hand over or release a hold an agent booked. It lapses at PayPal after 29 days, sandbox only.

## 🚀 Getting Started

### Prerequisites

Node 22 (the version CI uses), Python 3.12, a PayPal sandbox app, an Upstash Redis REST database and a Qwen (DashScope) key. Copy the variable names from [`jaminan/config.py`](jaminan/config.py) into `.env.local`.

### Installation

```bash
git clone https://github.com/edycutjong/jaminan && cd jaminan
npm install && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
npm run dev:api & npm run dev
```

Or skip setup: open the live [`/judge`](https://jaminan.edycu.dev/app/judge) route, which mints a fresh sandbox rental on one tap and lets you release the hold. Priced lines are in the recorded settlements in [`DEMO.md`](DEMO.md).

## 🧪 Testing & CI

```bash
make ci                                                                       # ruff, mypy, offline tests + coverage, pip-audit, eslint, tsc, build, npm audit
.venv/bin/python -m pytest -m "not sandbox and not live_model and not slow"   # offline suite only
.venv/bin/python -m pytest                                                    # + real sandbox, live Qwen, headless browser (needs credentials)
python scripts/e2e_live.py https://jaminan.edycu.dev/app --shots /tmp/jaminan-e2e   # live acceptance as two phones at 375 px
```

Commits use Angular prefixes (`feat:`, `fix:`, …); the `release` workflow derives the next semantic version from them — see [CONTRIBUTING](CONTRIBUTING.md).

The sandbox, live-model and browser tests need credentials, so CI runs the offline suite only (plus 8 Playwright checks on the built app with no credentials); run them yourself with the third command. Tests that pin a fixed defect are named for it. [`.env.example`](.env.example) lists every variable.

## 📁 Project Structure

```
app/        Next.js screens: renter (r/), shop (shop/), judge, integrations/verify
api/        FastAPI entry (Vercel Python function)
jaminan/    paypal.py · rules.py · gate.py · vision.py · service.py · tariff.py · store.py · mcp_server.py
fixtures/   published tariff, fine ceilings, shop and vehicle seed
tools/label labelling tool for the staged photo set
tests/      unit, contract, invariant and real-sandbox tests
.github/    CI, CodeQL, gitleaks, Dependabot, community files
```

## 🗺️ Roadmap

- [x] PayPal lifecycle: authorize, capture, void, vault, invoice, tracking
- [x] Pointed-claim rules in code, tariff-priced
- [x] Judge route with a fresh sandbox rental
- [ ] Vision benchmark on a staged scooter set
- [x] Reauthorize sandbox run (2026-10-23: 201 on two holds, second attempt 422)
- [x] MCP rental tool for booking agents ([`evidence/mcp/`](evidence/mcp/README.md))

## 📽️ Demo Materials

- Walkthrough, recorded PayPal settlements with ids, reproduce commands: [DEMO.md](DEMO.md)
- Live app: https://jaminan.edycu.dev/app
- Judge path: https://jaminan.edycu.dev/app/judge
- PayPal call log: https://jaminan.edycu.dev/app/integrations/verify (add `?rental=<id>` for one rental's calls and a live read-back)
- Landing page: https://jaminan.edycu.dev
- Pitch deck: https://jaminan.edycu.dev/pitch/ ([PDF](docs/pitch/jaminan-pitch-deck.pdf))

## 📄 License

[MIT](LICENSE)

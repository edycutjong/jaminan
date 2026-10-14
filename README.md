<div align="center">
  <img src="docs/assets/icon.svg" alt="Jaminan icon — a red stamp on the one accepted line, a green stamp releasing the rest of the hold" width="144">
  <h1>Jaminan 🛵</h1>
  <p><em>A PayPal hold that replaces the passport at the scooter-rental counter. The shop points, the shared baseline answers, and PayPal moves only the money the renter accepted.</em></p>
  <img src="docs/assets/readme-hero-animated.svg" alt="Jaminan — a PayPal hold instead of your passport. One red stamp for the cracked mirror; one green stamp releases the rest of the hold." width="100%">

  <br/>

  [![Live Demo](https://img.shields.io/badge/🚀_Live-Demo-06b6d4?style=for-the-badge)](https://jaminan.edycu.dev)
  [![Judge Path](https://img.shields.io/badge/⚖️_Judge-Path-f59e0b?style=for-the-badge)](https://jaminan.edycu.dev/judge)
  [![Landing Page](https://img.shields.io/badge/🧾_Landing-Page-1D7A4A?style=for-the-badge)](https://jaminan-landing.vercel.app)
  [![Pitch Deck](https://img.shields.io/badge/🗂️_Pitch-Deck-3346A6?style=for-the-badge)](https://jaminan-landing.vercel.app/pitch/)
  [![Built for PayPal AI Hackathon](https://img.shields.io/badge/Devpost-PayPal_AI_Hackathon-8b5cf6?style=for-the-badge)](https://paypalaihackathon.devpost.com/)

  <br/>

  ![Next.js](https://img.shields.io/badge/Next.js_16-black?style=flat&logo=next.js)
  ![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat&logo=typescript&logoColor=white)
  ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
  ![PayPal](https://img.shields.io/badge/PayPal_Sandbox-003087?style=flat&logo=paypal&logoColor=white)
  ![Upstash](https://img.shields.io/badge/Upstash_Redis-00E9A3?style=flat&logo=upstash&logoColor=black)
  [![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

</div>

---

## 💡 The Problem & Solution

### The Problem

In Bali and Jakarta the deposit on a rented scooter is often your passport (or a local's KTP). At return the shop points at a dent, the renter says it was already there, and whoever holds the document wins the argument. Neither side has evidence they both saw, and the "deposit" is a document, not money either side can trust.

### The Solution

Jaminan replaces the passport with a PayPal authorization and replaces the argument with a shared walkaround.

1. The renter scans the shop QR and gives **one PayPal approval** that authorizes the fee plus the deposit and saves the wallet for later fines. The fee is captured when both sides confirm the baseline at pickup; the deposit stays held.
2. A guided 8-angle walkaround records the scooter at pickup. Renter and shop confirm the baseline together.
3. At return **the owner points, the shared baseline answers.** The shop taps a mark and picks its `(part, damage_class)` from the published tariff. The model only answers what the pickup photos show; it never sets a price.
4. Code decides: no mark at return, visible at pickup, or not comparable at pickup all mean **cannot be charged**. Only clearly new damage becomes a priced line.
5. **The hold only pays lines the renter accepted.** Accepted lines become one capture with `final_capture=true`. A clean return voids the hold. A contested line goes out as an itemized PayPal invoice at its tariff price.

On the current deployment no vision model is pinned as benchmarked, so live rentals can release the hold but cannot price a damage line; priced lines are exercised in the unit and sandbox tests.

> **What the shared baseline can't show, nobody can charge.**

## 🏗️ Architecture & Tech Stack

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

The settle screen shows the status read back from PayPal after the call. Real-sandbox tests in [`tests/`](tests) cover authorize, vault, capture, void and invoice; tracking, webhooks and fine capture are covered by offline tests only.

### How this differs

| Existing approach | What it does | What it does not do |
|---|---|---|
| AI fleet-inspection products, as far as we found (e.g. [Monk](https://monk.ai), [Ravin](https://ravin.ai), [ProovStation](https://www.proovstation.com)) | Detect damage on vehicle photos | Move money: no hold, no capture, no release |
| Turo-style photo check-in | Both sides photograph the car on a marketplace | Bind a hold: photos are not tied to an authorization that only accepted lines can capture |
| A phone video before you ride | The renter's own record | Carry a co-signature, or get the passport back |

## 📊 Engineering Rigor

| Metric | Value |
|---|---|
| Tests collected | 101 (`pytest`): 92 offline unit, contract and invariant tests, 8 against the real PayPal sandbox (including `CAPTURED` and second-capture `422` read-backs), 1 live Qwen schema check |
| Claim-decision sweep | `decide_claim` run over 23,040 combinations of the five yes/no answers, serving model (pinned, other, none), confidence, a confirmed baseline mark, a low-comparability tile, three parts and five damage classes: every chargeable result satisfies every "new since pickup" condition and carries a tariff price ([`tests/test_invariants.py`](tests/test_invariants.py)) |
| Settle property test | up to 3,000 generated settlements (Hypothesis): the hold pays exactly the accepted chargeable lines at their tariff price, blocks exactly when a line is unanswered or mispriced, invoices only contested lines, and never exceeds the authorization |
| Offline coverage | 86% of `jaminan/` (`pytest --cov`, 1,415 statements) |
| CI | GitHub Actions: ruff, mypy, offline tests with coverage, pip-audit and an API boot smoke; eslint, `tsc`, production build and `npm audit`; gitleaks over full history; CodeQL (Python and TypeScript) once the repo is public; Dependabot monthly, grouped, no major bumps |
| Live acceptance script | `scripts/e2e_live.py` (375 px viewport) |
| Evidence pack | [`evidence/`](evidence): three recorded PayPal sandbox settlements call by call (`scripts/record_paypal_evidence.py`), the full test run, offline coverage and the live e2e log |
| Vision accuracy | **Not yet measured.** Benchmark on the staged scooter set is pending |

### Honest limits (6)

1. **Sandbox only.** Nothing here has moved live money; live vault and merchant-initiated eligibility are unverified.
2. **One merchant.** The demo uses a single sandbox merchant; a production path needs one onboarded merchant per shop.
3. **Wallet path only.** The sandbox app has no card processing, so cards are out of scope.
4. **Non-return is out of scope.** Jaminan covers damage and fines, not a scooter that never comes back.
5. **No vision accuracy claim yet.** Until the benchmark runs, no finding from a non-benchmarked model is chargeable.
6. **Reauthorize success is pending.** PayPal only allows it from Day 4; only the refusal fallback (re-authorize on the vaulted wallet, then void the old hold) is unit-tested; the sandbox run is scheduled for 2026-10-18 or later.

## 🚀 Getting Started

### Prerequisites

Node 20+, Python 3, a PayPal sandbox app, an Upstash Redis REST database and a Qwen (DashScope) key. Copy the variable names from [`jaminan/config.py`](jaminan/config.py) into `.env.local`.

### Installation

```bash
git clone https://github.com/edycutjong/jaminan && cd jaminan
npm install && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
npm run dev:api & npm run dev
```

Or skip setup: open the live [`/judge`](https://jaminan.edycu.dev/judge) route, which runs a fresh sandbox rental end to end.

## 🧪 Testing & CI

```bash
make ci                                                                       # ruff, mypy, offline tests + coverage, pip-audit, eslint, tsc, build, npm audit
.venv/bin/python -m pytest -m "not sandbox and not live_model and not slow"   # offline suite only
.venv/bin/python -m pytest                                                    # + real sandbox, live Qwen, headless browser (needs credentials)
python scripts/e2e_live.py https://jaminan.edycu.dev --shots /tmp/jaminan-e2e   # live acceptance as two phones at 375 px
```

The sandbox, live-model and browser tests need credentials, so CI runs the offline suite only; run them yourself with the third command. Tests that pin a fixed defect are named for it. [`.env.example`](.env.example) lists every variable.

## 📁 Project Structure

```
app/        Next.js screens: renter (r/), shop (shop/), judge, integrations/verify
api/        FastAPI entry (Vercel Python function)
jaminan/    paypal.py · rules.py · gate.py · vision.py · service.py · tariff.py · store.py
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
- [ ] Reauthorize sandbox run (on/after 2026-10-18)
- [ ] MCP rental tool for booking agents

## 📽️ Demo Materials

- Live app: https://jaminan.edycu.dev
- Judge path: https://jaminan.edycu.dev/judge
- Read-back stream: https://jaminan.edycu.dev/integrations/verify
- Landing page: https://jaminan-landing.vercel.app
- Pitch deck: https://jaminan-landing.vercel.app/pitch/ ([PDF](docs/pitch/jaminan-pitch-deck.pdf))

## 📄 License

[MIT](LICENSE)

# Contributing

Thanks for your interest in improving Jaminan.

## Getting started
1. Fork the repo and branch from `main`: `git checkout -b feat/your-change`
2. Install: `npm install && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`
3. Copy the env template: `cp .env.example .env.local` and fill in your own PayPal **sandbox** credentials
4. Run: `npm run dev:api & npm run dev`

## Before you open a PR
- `make ci` passes (ruff, mypy, offline tests with coverage, pip-audit, eslint, typecheck, build, npm audit).
- The money rules in `jaminan/rules.py` (I1–I5: the price comes from the tariff, only chargeable lines are paid, captures never exceed the authorization) have tests; a change to them needs a test that fails without it.
- Name a regression test after the defect it pins.
- Keep commits conventional (`feat:`, `fix:`, `docs:`, `chore:`).
- Never commit credentials. Sandbox only: this project does not move live money.

## Reporting bugs / requesting features
Open an issue with the provided templates, with repro steps and expected vs. actual behavior.

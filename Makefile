PY ?= .venv/bin/python
BIN ?= .venv/bin

.PHONY: help lint typecheck test test-coverage test-unit audit build ci e2e lighthouse sandbox-test

help:
	@echo "make ci            ruff, mypy, offline tests + coverage (100% gate), vitest lib/ (100% gate), pip-audit, eslint, tsc, build, npm audit"
	@echo "make sandbox-test  the full suite incl. real PayPal sandbox + live Qwen (needs credentials)"

lint:
	$(BIN)/ruff check .
	npm run lint

typecheck:
	$(BIN)/mypy
	npm run typecheck

test:
	$(PY) -m pytest -m "not sandbox and not live_model and not slow" -q

test-coverage:
	$(PY) -m pytest -m "not sandbox and not live_model and not slow" --cov=jaminan --cov-branch --cov-fail-under=100 --cov-report=term-missing

audit:
	$(BIN)/pip-audit --progress-spinner off
	npm run audit

build:
	npm run build

test-unit:
	npm run test:unit

ci: lint typecheck test-coverage test-unit audit build

e2e: build
	npm run e2e

lighthouse: build
	npm run lighthouse

sandbox-test:
	$(PY) -m pytest -q

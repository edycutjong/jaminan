PY ?= .venv/bin/python
BIN ?= .venv/bin

.PHONY: help lint typecheck test test-coverage audit build ci sandbox-test

help:
	@echo "make ci            ruff, mypy, offline tests + coverage, pip-audit, eslint, tsc, build, npm audit"
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
	$(PY) -m pytest -m "not sandbox and not live_model and not slow" --cov=jaminan --cov-report=term-missing

audit:
	$(BIN)/pip-audit --progress-spinner off
	npm audit --audit-level=high

build:
	npm run build

ci: lint typecheck test-coverage audit build

sandbox-test:
	$(PY) -m pytest -q

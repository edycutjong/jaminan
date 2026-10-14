import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jaminan.config import load_local_env  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "sandbox: hits the real PayPal sandbox (needs credentials)")
    config.addinivalue_line("markers", "live_model: calls the real Qwen vision API (needs a key)")


@pytest.fixture(scope="session")
def local_env():
    load_local_env()
    if not os.environ.get("PAYPAL_CLIENT_ID"):
        pytest.skip("no PayPal sandbox credentials in env or ~/.config/paypal/sandbox.env")
    return os.environ


@pytest.fixture(scope="session")
def sandbox_vault_id(local_env):
    """The spike buyer's saved wallet (S1, 2026-10-14). Override with JAMINAN_TEST_VAULT_ID."""
    return os.environ.get("JAMINAN_TEST_VAULT_ID") or os.environ.get("JUDGE_VAULT_IDS", "3ug34380pw497712d").split(",")[0]

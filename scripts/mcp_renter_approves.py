"""The human half of an agent booking, automated for the recorded run: open the approve_url an agent got from
start_rental, log in as the PayPal SANDBOX buyer, approve, and let Jaminan's return page authorize the hold —
exactly what the renter's phone does. Prints the return path with the renter key redacted. Sandbox only.

    .venv/bin/python scripts/mcp_renter_approves.py 'https://www.sandbox.paypal.com/checkoutnow?token=...'
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jaminan.config import load_local_env  # noqa: E402
from scripts.sandbox_buyer import approve_on_page  # noqa: E402


def main(url: str) -> None:
    from playwright.sync_api import sync_playwright
    load_local_env()
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        seen: list[int] = []  # the return page (/app/r/<id>/approved) calls /authorize with the renter's key
        pg.on("response", lambda r: seen.append(r.status) if r.url.endswith("/authorize") else None)
        pg.goto(url, wait_until="domcontentloaded", timeout=90_000)
        final = approve_on_page(pg)
        deadline = time.time() + 60
        while not seen and time.time() < deadline:
            pg.wait_for_timeout(500)
        print(f"return page: {re.sub(r'k=[^&]+', 'k=<renter-key>', final)}")
        print(f"authorize: HTTP {seen[0] if seen else 'not seen in 60 s'}")
        b.close()


if __name__ == "__main__":
    main(sys.argv[1])

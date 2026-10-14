"""Approve a PayPal sandbox order as the sandbox BUYER in a headless browser — the renter's single
approval, automated for tests, seeding and minting the judge wallet pool. Sandbox only."""
from __future__ import annotations

import os
import time


def approve(url: str, email: str | None = None, password: str | None = None, shot: str | None = None,
            timeout_s: int = 90) -> str:
    from playwright.sync_api import sync_playwright
    if "sandbox.paypal.com" not in url:
        raise RuntimeError("refusing to log a buyer in anywhere but sandbox.paypal.com")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
        final = approve_on_page(pg, email, password, timeout_s)
        if shot:
            pg.screenshot(path=shot)
        b.close()
        return final


def approve_on_page(pg, email: str | None = None, password: str | None = None, timeout_s: int = 90) -> str:
    """Log in and approve on an already-open PayPal sandbox page; returns the URL PayPal sends back to."""
    email = email or os.environ["PAYPAL_SANDBOX_BUYER_EMAIL"]
    password = password or os.environ["PAYPAL_SANDBOX_BUYER_PASSWORD"]
    if "sandbox.paypal.com" not in pg.url:
        raise RuntimeError("refusing to log a buyer in anywhere but sandbox.paypal.com")
    pg.wait_for_selector("#email", timeout=60000)
    pg.fill("#email", email)
    if pg.is_visible("#btnNext"):
        pg.click("#btnNext")
    pg.wait_for_selector("#password", state="visible", timeout=60000)
    pg.fill("#password", password)
    pg.click("#btnLogin")
    deadline = time.time() + timeout_s
    clicked = False
    while time.time() < deadline and not clicked:
        for sel in ["#payment-submit-btn", "[data-testid='submit-button-initial']", "#consentButton",
                    "button:has-text('Agree & Continue')", "button:has-text('Continue')", "button:has-text('Agree')"]:
            try:
                if pg.is_visible(sel):
                    pg.click(sel)
                    clicked = True
                    break
            except Exception:
                continue
        time.sleep(1)
    try:
        pg.wait_for_url(lambda u: "paypal.com" not in u, timeout=45000)
    except Exception:
        pass
    return pg.url

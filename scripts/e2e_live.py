"""Live end-to-end run of the one flow on a deployed URL, as two phones (shop + renter), 375 px wide.

    python scripts/e2e_live.py https://jaminan.vercel.app --shots /tmp/jaminan-e2e

The renter approves on the real PayPal sandbox page (sandbox buyer). The cameras are Chromium's fake
capture device fed a synthetic sharp test pattern (NOT a scooter): this exercises capture → frame gate →
storage → model call → PayPal, not vision accuracy (that is the bench on the staged photo set).
Prints one PASS/FAIL line per acceptance check; exits non-zero on any FAIL.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jaminan.config import load_local_env  # noqa: E402
from scripts.sandbox_buyer import approve_on_page  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  — {detail}" if detail else ""), flush=True)
    return ok


def y4m(path: Path, w: int = 1280, h: int = 960, frames: int = 4) -> Path:
    """A blocky random pattern: sharp edges (passes the blur gate), no clipped highlights."""
    rng = np.random.default_rng(42)
    small = rng.integers(50, 190, size=(h // 16, w // 16, 3)).astype(np.uint8)
    rgb = np.asarray(Image.fromarray(small).resize((w, h), Image.NEAREST)).astype(np.float32)
    y = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).clip(0, 255).astype(np.uint8)
    u = np.full((h // 2, w // 2), 128, np.uint8)
    with path.open("wb") as f:
        f.write(f"YUV4MPEG2 W{w} H{h} F10:1 Ip A1:1 C420jpeg\n".encode())
        for _ in range(frames):
            f.write(b"FRAME\n" + y.tobytes() + u.tobytes() + u.tobytes())
    return path


def walkaround(pg, label: str, shots: Path) -> bool:
    for a in range(1, 9):
        pg.wait_for_selector(".shutter:not([disabled])", timeout=30000)
        pg.click(".shutter")
        pg.wait_for_function("() => !document.querySelector('.spin')", timeout=60000)
        if a == 8 and pg.locator(".shutter").count() == 0:
            break  # the walkaround hands over to the next step once all 8 angles are in
        toast = pg.locator(".toast").last.inner_text(timeout=5000) if pg.locator(".toast").count() else ""
        if "✓" not in toast:
            return check(f"{label}: angle {a} accepted by the frame gate", False, toast)
    pg.screenshot(path=str(shots / f"{label}-walkaround.png"), full_page=True)
    return check(f"{label}: 8 angles captured in-app, gated and hashed", True)


def GET(rid: str) -> str:
    """JS that reads the rental with whichever party key this phone holds."""
    return (f"() => fetch('/api/rentals/{rid}', {{headers: {{'X-Jaminan-Key': localStorage.getItem('jaminan:key:{rid}:shop')"
            f" || localStorage.getItem('jaminan:key:{rid}:renter')}}}}).then(r => r.json())")


def no_hscroll(pg, name: str) -> None:
    w = pg.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
    check(f"375 px: no horizontal scroll on {name}", w[0] <= w[1], f"scrollWidth {w[0]} vs {w[1]}")


def main(base: str, shots: Path) -> int:
    from playwright.sync_api import sync_playwright
    load_local_env()
    shots.mkdir(parents=True, exist_ok=True)
    cam = y4m(shots / "pattern.y4m")
    args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", f"--use-file-for-fake-video-capture={cam}"]
    phone = {"viewport": {"width": 375, "height": 812}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True,
             "permissions": ["camera"]}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=args)
        shop, renter = b.new_context(**phone), b.new_context(**phone)
        sp, rp = shop.new_page(), renter.new_page()
        for pg in (sp, rp):
            pg.set_default_timeout(45000)

        # 1 counter → QR
        sp.goto(f"{base}/shop")
        sp.click("text=Buat QR untuk penyewa")
        sp.wait_for_selector(".qr img")
        link = sp.locator("a", has_text="buka di ponsel ini").get_attribute("href")
        rid = link.split("/r/")[1].split("?")[0]
        check("counter: new rental + renter QR", bool(rid), rid)
        sp.screenshot(path=str(shots / "1-counter.png"), full_page=True)
        no_hscroll(sp, "/shop")

        # 2 renter: rental page → ONE PayPal approval
        rp.goto(link)
        rp.wait_for_selector("text=Approve with PayPal")
        check("rental page shows the vault consent copy before PayPal",
              rp.locator("text=renew this rental").count() > 0)
        rp.screenshot(path=str(shots / "2-rental-page.png"), full_page=True)
        no_hscroll(rp, "/r/[id] rental page")
        rp.click("text=Approve with PayPal")
        rp.wait_for_url("**sandbox.paypal.com/**", timeout=60000)
        approve_on_page(rp)
        rp.wait_for_url(f"**/r/{rid}", timeout=90000)
        rp.wait_for_selector("text=Pickup walkaround", timeout=60000)
        st = rp.evaluate(GET(rid))
        check("one approval → authorization + saved wallet", st["state"] == "APPROVED" and bool(st.get("vault_id")),
              f"{st['state']} auth {st.get('authorization_id')}")

        # 3 pickup walkaround + pre-marks + confirm
        walkaround(rp, "pickup", shots)
        rp.click("text=List the marks already on the scooter")
        rp.wait_for_selector("text=I confirm these photos and marks", timeout=120000)
        rp.screenshot(path=str(shots / "3-baseline-renter.png"), full_page=True)
        rp.click("text=I confirm these photos and marks")
        rp.wait_for_selector("text=Waiting for the shop", timeout=30000)
        sp.goto(f"{base}/shop/r/{rid}")
        sp.wait_for_selector("text=Konfirmasi foto awal", timeout=30000)
        sp.screenshot(path=str(shots / "4-baseline-shop.png"), full_page=True)
        no_hscroll(sp, "/shop/r/[id] baseline")
        sp.click("text=Konfirmasi foto awal")
        sp.wait_for_selector("text=Motor sedang jalan", timeout=60000)
        st = sp.evaluate(GET(rid))
        check("both confirm → fee captured (final_capture=false), tracking written",
              st["state"] == "OUT" and st.get("auth_status") == "PARTIALLY_CAPTURED" and str(st.get("tracking_number", "")).startswith("JMN-"),
              f"{st.get('auth_status')} {st.get('tracking_number')}")

        # 4 return walkaround on the shop phone → suggestions → a pointed claim
        walkaround(sp, "return", shots)
        sp.click("text=Selesai foto kembali")
        sp.wait_for_selector("text=Cek pengembalian", timeout=60000)
        sp.wait_for_function("() => !document.querySelector('.spin')", timeout=120000)
        box = sp.locator(".frame").bounding_box()
        sp.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
        sp.wait_for_selector(".picker button")
        sp.locator(".picker button").first.click()
        sp.wait_for_selector("[role=status] strong", timeout=120000)
        sp.wait_for_function("() => [...document.querySelectorAll('.crop img')].every(i => i.complete && i.naturalWidth > 0)", timeout=30000)
        check("claim answer shows the pickup crop beside the return crop", sp.locator(".crop img").count() >= 2)
        answer = sp.locator("[role=status] strong").nth(1).inner_text()
        sp.screenshot(path=str(shots / "5-return-claim.png"), full_page=True)
        no_hscroll(sp, "/shop/r/[id] return")
        st = sp.evaluate(GET(rid))
        f = st["findings"][-1]
        check("pointed claim → model answer recorded with the serving model id", bool(f.get("model")) or bool(f.get("model_error")),
              f"{f['disposition']} · model {f.get('model')} · {answer}")
        check("no benchmarked model pinned → the claim cannot be charged",
              st.get("benchmarked_model") is not None or f["disposition"] != "chargeable", f["disposition"])

        # 5 clean release → PayPal read-back
        sp.click("text=Lepas jaminan")
        sp.wait_for_selector(".stamp.released", timeout=60000)
        st = sp.evaluate(GET(rid))
        check("release → void, stamp fires on PayPal read-back VOIDED",
              (st.get("settlement") or {}).get("auth_read_back") == "VOIDED", json.dumps(st.get("settlement"))[:160])
        sp.screenshot(path=str(shots / "6-released-shop.png"), full_page=True)
        rp.reload()
        rp.wait_for_selector("text=Receipt", timeout=30000)
        rp.screenshot(path=str(shots / "7-receipt.png"), full_page=True)
        no_hscroll(rp, "/r/[id] receipt")
        check("renter receipt shows the green released stamp", rp.locator(".stamp.released").count() == 1)

        # 6 verify page shows the calls with debug ids
        rp.goto(f"{base}/integrations/verify?rental={rid}")
        rp.wait_for_selector("text=Read-back now", timeout=30000)
        rows = rp.locator("tbody tr").count()
        rp.screenshot(path=str(shots / "8-verify.png"), full_page=True)
        check("/integrations/verify lists the rental's PayPal calls + read-back", rows >= 6, f"{rows} rows")
        rp.goto(f"{base}/r/{rid}/evidence")
        rp.wait_for_selector("text=Evidence", timeout=30000)
        check("evidence pack renders hashes, model ids and PayPal debug ids", rp.locator("tbody tr").count() >= 6)
        b.close()
    fails = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed · rental {rid}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "https://jaminan.vercel.app",
                  Path(sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--shots" else "/tmp/jaminan-e2e")))

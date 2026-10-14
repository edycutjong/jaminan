"""Deterministic frame gate — numpy + Pillow, no model call (W4).

Every frame is resized to a fixed 1280 px width first, so thresholds mean the same thing on every phone.
Blur = variance of the Laplacian; glare = fraction of clipped highlights. The same 4×4 tiles give a
per-region comparability map: tiles that are blurred or glared at PICKUP are shown to the shop at
baseline confirm ("marks here can't be charged later — ask for a retake?") and a later claim inside
them is `not_comparable`.

Thresholds are UNCALIBRATED defaults until the staged dev set calibrates them (bench).
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageOps

WIDTH = 1280
GRID = 4
THRESHOLDS = {
    "blur_min_var": 40.0,        # whole-frame Laplacian variance below this → blurry
    "glare_max_frac": 0.20,      # whole-frame clipped-highlight fraction above this → glare
    "tile_blur_min_var": 15.0,   # tile-level → low comparability
    "tile_glare_max_frac": 0.25,
    "clip_level": 250,           # 8-bit luma at or above this counts as clipped
    "min_short_side": 480,
}
MAX_JPEG_BYTES = 150_000


@dataclass
class GateResult:
    ok: bool
    reason: str | None
    blur_var: float
    glare_frac: float
    width: int
    height: int
    low_tiles: list[list[float]] = field(default_factory=list)   # normalized [x, y, w, h]
    tile_scores: list[dict] = field(default_factory=list)
    sha256: str = ""

    def public(self) -> dict:
        return {"ok": self.ok, "reason": self.reason, "blur_var": round(self.blur_var, 1),
                "glare_frac": round(self.glare_frac, 4), "width": self.width, "height": self.height,
                "low_tiles": self.low_tiles, "sha256": self.sha256}


def normalize(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB")
    if img.width != WIDTH:
        img = img.resize((WIDTH, max(1, round(img.height * WIDTH / img.width))), Image.LANCZOS)
    return img


def to_jpeg(img: Image.Image, max_bytes: int = MAX_JPEG_BYTES) -> bytes:
    for q in (85, 78, 70, 62, 55, 48, 40):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= max_bytes:
            return buf.getvalue()
    small = img.resize((img.width * 3 // 4, img.height * 3 // 4), Image.LANCZOS)
    return to_jpeg(small, max_bytes)


def _laplacian_var(gray: np.ndarray) -> float:
    g = gray.astype(np.float32)
    lap = (g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4 * g[1:-1, 1:-1])
    return float(lap.var()) if lap.size else 0.0


def check(data: bytes, thresholds: dict | None = None) -> tuple[GateResult, bytes]:
    """Returns the gate verdict and the normalized JPEG (≤ 150 KB) that is stored and hashed."""
    t = {**THRESHOLDS, **(thresholds or {})}
    img = normalize(data)
    jpeg = to_jpeg(img)
    gray = np.asarray(img.convert("L"))
    h, w = gray.shape
    blur = _laplacian_var(gray)
    glare = float((gray >= t["clip_level"]).mean())
    low, scores = [], []
    th, tw = h // GRID, w // GRID
    for r in range(GRID):
        for c in range(GRID):
            tile = gray[r * th:(r + 1) * th, c * tw:(c + 1) * tw]
            tv, tg = _laplacian_var(tile), float((tile >= t["clip_level"]).mean())
            box = [round(c / GRID, 4), round(r / GRID, 4), round(1 / GRID, 4), round(1 / GRID, 4)]
            bad = tv < t["tile_blur_min_var"] or tg > t["tile_glare_max_frac"]
            scores.append({"box": box, "blur_var": round(tv, 1), "glare_frac": round(tg, 4), "low": bad})
            if bad:
                low.append(box)
    reason = None
    if min(img.width, img.height) < t["min_short_side"]:
        reason = "too_small"
    elif blur < t["blur_min_var"]:
        reason = "blurry"
    elif glare > t["glare_max_frac"]:
        reason = "glare"
    return GateResult(ok=reason is None, reason=reason, blur_var=blur, glare_frac=glare, width=img.width,
                      height=img.height, low_tiles=low, tile_scores=scores,
                      sha256=hashlib.sha256(jpeg).hexdigest()), jpeg


def crop(jpeg: bytes, bbox: list[float], scale: float = 1.0, min_px: int = 192) -> tuple[bytes, list[float]]:
    """Crop a normalized box (optionally grown around its centre by `scale`) — returns the JPEG crop and
    the normalized region actually cropped, so a box the model returns inside it maps back to the frame."""
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    x, y, bw, bh = bbox
    cx, cy = x + bw / 2, y + bh / 2
    bw, bh = bw * scale, bh * scale
    bw, bh = max(bw, min_px / img.width), max(bh, min_px / img.height)
    x0, y0 = max(0.0, cx - bw / 2), max(0.0, cy - bh / 2)
    x1, y1 = min(1.0, cx + bw / 2), min(1.0, cy + bh / 2)
    box = (int(x0 * img.width), int(y0 * img.height), int(x1 * img.width), int(y1 * img.height))
    out = io.BytesIO()
    img.crop(box).save(out, "JPEG", quality=88)
    return out.getvalue(), [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]


def map_back(inner: list[float], region: list[float]) -> list[float]:
    """A box normalized inside `region` → normalized in the full frame."""
    rx, ry, rw, rh = region
    x, y, w, h = inner
    return [round(rx + x * rw, 4), round(ry + y * rh, 4), round(w * rw, 4), round(h * rh, 4)]

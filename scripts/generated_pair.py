"""Record the vision model's real answers on the AI-generated test pair into evidence/generated-pair/.

    .venv/bin/python scripts/generated_pair.py [--repeats 3]

The two images in evidence/generated-pair/ are AI-GENERATED TEST IMAGES, not photographs (see GENERATION.json there):
a pickup frame from qwen-image-2.0 and a return frame edited from it by wan2.6-image (both mirrors removed). Each frame
goes through the same frame gate as an upload, and each claim through the same path as `Service.claim`: the return
crop around the tap (x2), the pickup search area (x4), `Vision.claim`, then `rules.decide_claim` with the configured
benchmarked model. That model is empty, so every line ends `comparison_unavailable` and nothing is charged.
`model_reading` is what the same rules would read from the answer if this model were pinned. It is not a benchmark:
one angle, two claims, AI-generated images.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jaminan import gate, rules, tariff  # noqa: E402
from jaminan.config import Settings, load_local_env  # noqa: E402
from jaminan.vision import from_settings  # noqa: E402

DIR = ROOT / "evidence" / "generated-pair"
ANGLE = 2  # front-left three-quarter
FRAMES = {"pickup": "pickup-front-left.png", "return": "return-front-left.png"}
# Tap boxes pointed by the builder from GENERATION.json's ground truth, [x, y, w, h] normalized on the frame.
CLAIMS = [
    {"id": "C1", "expected": "old", "part": "front_fairing", "damage_class": "dent", "bbox": [0.435, 0.425, 0.075, 0.135],
     "note": "the grey scuff on the front-left fairing, visible in both images. The tariff has no front_fairing/scuff "
             "line, so the shop taps the nearest priced line on that part (dent): an over-claim on an old mark."},
    {"id": "C2", "expected": "new", "part": "mirror", "damage_class": "missing_part", "bbox": [0.36, 0.0, 0.36, 0.24],
     "note": "both rear-view mirrors missing at return; the box covers both mirror mounts and where the mirrors stood."},
]
READING = {"excluded_baseline": "old", "chargeable": "new", "evidence_only": "new", "class_mismatch": "new, other class",
           "no_mark": "no mark", "not_comparable": "not comparable", "retake": "retake",
           "comparison_unavailable": "no answer"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    a = ap.parse_args()
    load_local_env()
    s = Settings()
    vision = from_settings(s)
    tv = tariff.load("tv1")
    frames, jpegs = {}, {}
    for phase, name in FRAMES.items():
        g, jpeg = gate.check((DIR / name).read_bytes())
        frames[phase] = {"file": name, "gate": {"ok": g.ok, "reason": g.reason, "blur_var": round(g.blur_var, 1),
                                                "glare_frac": round(g.glare_frac, 4), "width": g.width,
                                                "height": g.height, "low_tiles": g.low_tiles, "sha256": g.sha256}}
        jpegs[phase] = (jpeg, g.low_tiles)
    rejected = [p for p, f in frames.items() if not f["gate"]["ok"]]
    claims = []
    for c in CLAIMS if not rejected else []:  # an upload the gate rejects is never compared: no model call either
        ret_crop, ret_region = gate.crop(jpegs["return"][0], c["bbox"], scale=2.0)
        pick_area, pick_region = gate.crop(jpegs["pickup"][0], c["bbox"], scale=4.0)
        price = tv.price(c["part"], c["damage_class"])
        runs = []
        for i in range(a.repeats):
            at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            call = vision.claim(ret_crop, pick_area, [], c["part"], c["damage_class"], ANGLE)
            ans = call.parsed.model_dump() if call.ok else None
            common = dict(answer=ans, serving_model=call.model, part=c["part"], damage_class=c["damage_class"],
                          angle=ANGLE, tap_bbox=c["bbox"], price_cents=price, baseline_marks=[],
                          pickup_low_tiles=jpegs["pickup"][1], chargeable_classes=s.chargeable_classes,
                          confidence_floor=s.confidence_floor)
            d = rules.decide_claim(benchmarked_model=s.benchmarked_model, **common)
            shadow = rules.decide_claim(benchmarked_model=call.model or "", **common) if ans else d
            runs.append({"repeat": i + 1, "at": at, **call.meta(), "answer": ans,
                         "disposition": d.disposition, "reason": d.reason, "answer_text": d.text(c["damage_class"]),
                         "price_cents": None,
                         "model_reading": READING[shadow.disposition], "reading_disposition": shadow.disposition,
                         "matches_expected": READING[shadow.disposition] == c["expected"]})
            print(c["id"], i + 1, call.model, call.request_id, call.error, d.disposition, "reading:",
                  READING[shadow.disposition], flush=True)
        claims.append({**c, "angle": ANGLE, "return_region": ret_region, "pickup_region": pick_region,
                       "tariff_price_cents": price, "runs": runs})
    out = {"kind": "AI-generated test images (not photographs) — recorded model answers, not a benchmark",
           "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "requested_model": s.vision_model, "benchmarked_model": s.benchmarked_model or None,
           "confidence_floor": s.confidence_floor, "chargeable_classes": list(s.chargeable_classes),
           "generation": "GENERATION.json", "frames": frames, "claims": claims}
    if rejected:
        out["stopped"] = f"frame gate rejected the {' and '.join(rejected)} frame: an upload would be refused, so no claim was compared"
    day = f"{datetime.now():%Y-%m-%d}"  # local (WIB) date; times inside are UTC
    path, n = DIR / f"run-{day}.json", 1
    while path.exists():  # a recorded run is evidence: another run that day gets its own file, never overwrites one
        path, n = DIR / f"run-{day}-{n}.json", n + 1
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print("wrote", path.relative_to(ROOT))
    if rejected:
        raise SystemExit(out["stopped"])


if __name__ == "__main__":
    main()

"""Partial vision check on public single photos (Wikimedia Commons) into evidence/public-photo-bench/.

    .venv/bin/python scripts/public_photo_bench.py [--repeats 3] [--workers 4]

Not the staged-scooter benchmark. Each image is one real photograph, so pickup and return are the SAME photo: it checks
that the model does not call an old mark (or a clean spot) "new", and how it names a mark's damage class. It cannot
measure new damage between two different photos of one vehicle. Labels (labels.csv) were frozen in git before any model
call; the prompts are the app's own, unchanged, and nothing is tuned on this set.

  T1 old-mark: every labelled mark is pointed with its labelled part + class. Right answer: visible at pickup (old).
  T2 clean spot: one undamaged spot per clean image, claimed as a scuff on that part. Right answer: anything but new.
  T3 damage reading: the pickup pre-mark call on the single photo; the class of the model's mark that overlaps the
     label most is compared with the labelled class (no bar).

Each frame goes through the upload frame gate; T1/T2 use the same crops (`gate.crop` x2 / x4), `Vision.claim` and
`rules.decide_claim` steps as a claim, run from this script. The benchmarked model is empty, so every line would end
`comparison_unavailable`; `reading` is what the same rules read from the answer if the serving model were pinned.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jaminan import gate, rules, tariff  # noqa: E402
from jaminan.config import Settings, load_local_env  # noqa: E402
from jaminan.vision import from_settings  # noqa: E402

DIR = ROOT / "evidence" / "public-photo-bench"
READING = {"excluded_baseline": "old", "chargeable": "new", "evidence_only": "new", "class_mismatch": "new, other class",
           "no_mark": "no mark", "not_comparable": "not comparable", "retake": "retake",
           "comparison_unavailable": "no answer"}
NEW = {"new", "new, other class"}
T2_CLASS = "scuff"  # the clean spot is claimed as the commonest over-claim


def load_labels(path: Path) -> list[dict]:
    rows = list(csv.DictReader(path.open()))
    for r in rows:
        r["angle"] = int(r["angle"])
        r["bbox"] = [float(r[k]) for k in ("x", "y", "w", "h")]
    return rows


def percentile(values: list[int], q: float) -> int | None:
    """Nearest-rank percentile (q in 0-100)."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, min(len(s) - 1, math.ceil(len(s) * q / 100) - 1))]


def best_overlap(label_box: list[float], marks: list[dict]) -> dict | None:
    """The model mark covering most of the labelled box (either way round); None if nothing touches it."""
    best, score = None, 0.0
    for m in marks:
        s = max(rules.bbox_overlap(label_box, m["bbox"]), rules.bbox_overlap(m["bbox"], label_box))
        if s > score:
            best, score = m, s
    return best


def summarize_claims(items: list[dict], wrong: set[str]) -> dict:
    """Counts over every call, plus per-item flips (readings that differ across repeats)."""
    readings = [r["reading"] for it in items for r in it["runs"]]
    n = len(readings)
    bad = sum(1 for x in readings if x in wrong)
    flips = [it["id"] for it in items if len({r["reading"] for r in it["runs"]}) > 1]
    return {"items": len(items), "calls": n, "false_new": bad, "false_new_rate": round(bad / n, 4) if n else None,
            "items_with_any_false_new": sum(1 for it in items if any(r["reading"] in wrong for r in it["runs"])),
            "readings": dict(Counter(readings).most_common()), "flipped_items": flips, "bar": "0 false new",
            "pass": bad == 0 and n > 0}


def summarize_t3(items: list[dict]) -> dict:
    pairs = [(it["damage_class"], r["predicted"]) for it in items for r in it["runs"]]
    agree = sum(1 for a, b in pairs if a == b)
    confusion: dict[str, dict[str, int]] = {}
    for a, b in pairs:
        confusion.setdefault(a, {}).setdefault(b, 0)
        confusion[a][b] += 1
    return {"marks": len(items), "readings": len(pairs), "class_agrees": agree,
            "not_found": sum(1 for _, b in pairs if b == "not_found"),
            "no_answer": sum(1 for _, b in pairs if b == "no_answer"), "confusion": confusion, "bar": None}


def labels_commit(path: Path) -> str | None:
    """The commit that added labels.csv (frozen before any model call)."""
    try:
        out = subprocess.run(["git", "-C", str(path.parent), "log", "--format=%H", "--diff-filter=A", "--", path.name],
                             capture_output=True, text=True, timeout=20).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    return out[-1] if out else None


def run(vision, s: Settings, labels: list[dict], repeats: int, workers: int) -> dict:
    tv = tariff.load("tv1")
    frames: dict[str, dict] = {}
    for img in sorted({r["image"] for r in labels}):
        g, jpeg = gate.check((DIR / "photos" / f"{img}.jpg").read_bytes())
        frames[img] = {"gate": {"ok": g.ok, "reason": g.reason, "blur_var": round(g.blur_var, 1),
                                "glare_frac": round(g.glare_frac, 4), "width": g.width, "height": g.height,
                                "sha256": g.sha256}, "jpeg": jpeg, "low_tiles": g.low_tiles}
    usable = [r for r in labels if frames[r["image"]]["gate"]["ok"]]  # a frame the gate rejects is never compared

    def claim(r: dict, cls: str, rep: int) -> dict:
        f = frames[r["image"]]
        ret_crop, _ = gate.crop(f["jpeg"], r["bbox"], scale=2.0)
        pick_area, _ = gate.crop(f["jpeg"], r["bbox"], scale=4.0)
        at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        call = vision.claim(ret_crop, pick_area, [], r["part"], cls, r["angle"])
        ans = call.parsed.model_dump() if call.ok else None
        common = dict(answer=ans, part=r["part"], damage_class=cls, angle=r["angle"], tap_bbox=r["bbox"],
                      price_cents=tv.price(r["part"], cls), baseline_marks=[], pickup_low_tiles=f["low_tiles"],
                      chargeable_classes=s.chargeable_classes, confidence_floor=s.confidence_floor)
        d = rules.decide_claim(benchmarked_model=s.benchmarked_model, serving_model=call.model, **common)
        shadow = rules.decide_claim(benchmarked_model=call.model or "", serving_model=call.model, **common) if ans else d
        return {"repeat": rep, "at": at, **call.meta(), "answer": ans, "disposition": d.disposition,
                "reading_disposition": shadow.disposition, "reading": READING[shadow.disposition]}

    def premark(img: str, rep: int) -> dict:
        f = frames[img]
        angle = next(r["angle"] for r in usable if r["image"] == img)
        at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        call = vision.premark(f["jpeg"], angle)
        marks = [m.model_dump() for m in call.parsed.marks] if call.ok else None
        return {"repeat": rep, "at": at, **call.meta(), "marks": marks}

    t1 = [r for r in usable if r["kind"] == "mark"]
    t2 = [r for r in usable if r["kind"] == "clean_spot"]
    t3_imgs = sorted({r["image"] for r in t1})
    jobs = [("t1", r["mark"], (lambda r=r, i=i: claim(r, r["damage_class"], i))) for r in t1 for i in range(1, repeats + 1)]
    jobs += [("t2", r["mark"], (lambda r=r, i=i: claim(r, T2_CLASS, i))) for r in t2 for i in range(1, repeats + 1)]
    jobs += [("t3", img, (lambda img=img, i=i: premark(img, i))) for img in t3_imgs for i in range(1, repeats + 1)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda j: (j[0], j[1], j[2]()), jobs))
    by: dict[tuple[str, str], list[dict]] = {}
    for test, key, res in results:
        by.setdefault((test, key), []).append(res)
        print(test, key, res["repeat"], res.get("model"), res.get("error") or res.get("reading", ""), flush=True)

    def item(r: dict, test: str, cls: str) -> dict:
        return {"id": r["mark"], "image": r["image"], "vehicle": r["vehicle"], "angle": r["angle"], "part": r["part"],
                "damage_class": cls, "tap_bbox": r["bbox"], "runs": sorted(by[(test, r["mark"])], key=lambda x: x["repeat"])}

    t1_items = [item(r, "t1", r["damage_class"]) for r in t1]
    t2_items = [item(r, "t2", T2_CLASS) for r in t2]
    t3_calls = {img: sorted(by[("t3", img)], key=lambda x: x["repeat"]) for img in t3_imgs}
    t3_items = []
    for r in t1:
        runs = []
        for c in t3_calls[r["image"]]:
            if c["marks"] is None:
                runs.append({"repeat": c["repeat"], "predicted": "no_answer", "matched": None})
                continue
            m = best_overlap(r["bbox"], c["marks"])
            runs.append({"repeat": c["repeat"], "predicted": m["damage_class"] if m else "not_found",
                         "matched": m})
        t3_items.append({"id": r["mark"], "image": r["image"], "part": r["part"], "damage_class": r["damage_class"],
                         "runs": runs})
    ms = [res["ms"] for _, _, res in results if res.get("ms") is not None]
    served = Counter(res.get("model") for _, _, res in results)
    errors = Counter(res["error"].split(":")[0] for _, _, res in results if res.get("error"))
    for f in frames.values():
        f.pop("jpeg")
    return {
        "kind": "partial vision check on public single photos (Wikimedia Commons) — not the staged-scooter benchmark",
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "requested_model": s.vision_model, "served_models": dict(served), "benchmarked_model": s.benchmarked_model or None,
        "confidence_floor": s.confidence_floor, "chargeable_classes": list(s.chargeable_classes), "repeats": repeats,
        "labels": {"file": "labels.csv", "sha256": hashlib.sha256((DIR / "labels.csv").read_bytes()).hexdigest(),
                   "frozen_in_commit": labels_commit(DIR / "labels.csv"),
                   "drawn_by": "the builder's agent (Claude), not an independent annotator"},
        "frames": {k: {"gate": v["gate"]} for k, v in frames.items()},
        "gate_rejected": sorted(k for k, v in frames.items() if not v["gate"]["ok"]),
        "summary": {"t1_old_mark": summarize_claims(t1_items, NEW), "t2_clean_spot": summarize_claims(t2_items, NEW),
                    "t3_damage_reading": summarize_t3(t3_items),
                    "latency_ms": {"calls": len(ms), "p50": percentile(ms, 50), "p95": percentile(ms, 95)},
                    "call_errors": dict(errors)},
        "t1_old_mark": t1_items, "t2_clean_spot": t2_items, "t3_damage_reading": t3_items, "t3_calls": t3_calls,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    load_local_env()
    s = Settings()
    out = run(from_settings(s), s, load_labels(DIR / "labels.csv"), a.repeats, a.workers)
    day = f"{datetime.now():%Y-%m-%d}"  # local (WIB) date; times inside are UTC
    path, n = DIR / f"run-{day}.json", 1
    while path.exists():  # a recorded run is evidence: another run that day gets its own file, never overwrites one
        path, n = DIR / f"run-{day}-{n}.json", n + 1
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print("wrote", path.relative_to(ROOT))
    print(json.dumps(out["summary"], indent=1))


if __name__ == "__main__":
    main()

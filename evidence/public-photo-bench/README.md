# Partial vision check on public single photos — FAIL

**Result: `qwen3-vl-plus` fails both bars.** Shown the same real photograph as both the pickup and the return image, it
called an old mark "new" in **71 of 105** answers and a clean spot "new" in **66 of 66**. The bar for both tests is 0. This
is why no vision model is pinned as benchmarked: in the app those answers end `comparison_unavailable` and charge nothing.

This is **not** the staged-scooter benchmark, which has not run yet. It is a held-out check on public photos, run once
with the app's prompts unchanged and nothing tuned on this set. Raw record: [`run-2026-10-25.json`](run-2026-10-25.json).

## The set

| | Images | Vehicles | Labelled |
|---|---|---|---|
| Damaged | 26 | 18 motor scooters, 2 mopeds, 6 motorcycles | 37 marks (box + part + damage class) |
| Clean | 22 | 22 motor scooters, from the Commons categories Honda BeAT, Honda Vario, Honda Scoopy, Yamaha NMAX and Yamaha Mio | one undamaged spot each |

- **Source:** Wikimedia Commons, real photographs only (renders, drawings and composites skipped). Licences CC BY, CC BY-SA
  and CC0 only, each kept with its image: [ATTRIBUTION.md](ATTRIBUTION.md). Page URL, author, licence, original size, the
  Commons SHA-1 and the SHA-256 of the stored copy: [sources.csv](sources.csv).
- **Labels** ([labels.csv](labels.csv)) were **drawn by the builder's agent (Claude), not by an independent annotator**,
  from each image and its Commons description. Ambiguous images were dropped rather than guessed. The labels were committed
  in `a2f7d9c` before any model call; the run records that commit and the file's SHA-256.
- **Frame gate:** 1 of 48 images was rejected as blurry (`d29`, blur variance 38.3 < 40). An upload the gate rejects is
  never compared, so its 2 marks are not scored. T1 therefore covers **35 marks on 25 images**.
- **Shortfall:** the target was ≥ 40 damaged images. After searching Commons by category and by keyword in several
  languages, 26 usable ones remained once ambiguous images were dropped.

## Results (`qwen3-vl-plus`, 3 repeats, 246 calls, all served by `qwen3-vl-plus`)

| Test | n | Bar | Result | |
|---|---|---|---|---|
| **T1 old mark:** pickup = return = one photo; each labelled mark pointed as its labelled part + class. Right answer: visible at pickup | 35 marks × 3 = 105 answers | 0 false "new" | **71 false "new" (67.6%)**: 64 "new" + 7 "new, other class". 26 "old", 6 "no mark", 2 "retake". 27 of 35 marks drew at least one false "new"; 8 marks changed answer across repeats | **FAIL** |
| **T2 clean spot:** same photo both sides, an undamaged spot claimed as a scuff | 22 spots × 3 = 66 answers | 0 false "new" | **66 false "new" (100%)**, no flips | **FAIL** |
| **T3 damage reading:** the pickup pre-mark call on the single photo; the class of the model mark overlapping the label most | 35 marks × 3 = 105 readings | none | class agrees **36 of 105**; no overlapping mark 6; no answer 9 (6 of 75 pre-mark calls failed the schema) | — |
| Latency | 246 calls | p95 ≤ 60 s | p50 **2,703 ms**, p95 **8,601 ms** | |

A "reading" is what `rules.decide_claim` would decide from the answer **if** the serving model were pinned. It is not
what happened: no model is pinned, so every T1 and T2 line was recorded as `comparison_unavailable`. Even pinned, none of
the 137 false "new" answers would have been priced. Each one ends `evidence_only` or `class_mismatch` (field
`reading_disposition` in the run), because of the tariff, the enabled classes and the 0.7 confidence floor, not because the
model got it right.

T1 false "new" by labelled class: scuff 25 of 42, broken part 18 of 24, missing part 28 of 39. By vehicle: motor scooters
42 of 72, motorcycles 21 of 24, mopeds 8 of 9.

T3 confusion (rows = label, columns = the model's class):

| Label ↓ / model → | missing part | broken part | dent | crack | scuff | no overlapping mark | no answer |
|---|---|---|---|---|---|---|---|
| missing part (39) | 9 | 15 | 3 | 0 | 4 | 3 | 5 |
| broken part (24) | 5 | 16 | 1 | 0 | 2 | 0 | 0 |
| scuff (42) | 0 | 3 | 18 | 3 | 11 | 3 | 4 |

## What the answers show

In every one of the 137 false "new" answers the model said the two images show the same view, that there is a mark at
the tap, that the pickup image is clear enough at that spot, and that the mark is not visible there. Its rationales read like "the same area in the pickup image is clear
and shows no such mark", although the pickup image is the same photo. The pickup image is the same region cropped twice as
wide (`gate.crop` ×4 against ×2, the same crops as `Service.claim`), so the mark is smaller in it but present.

## What this does NOT measure

- New damage between two different photos of the same vehicle, which is the real claim. With one photo per vehicle,
  only the "old mark" and "clean spot" answers can be checked.
- Scooters in Jakarta light, at the shop, through the in-app camera with its eight framed angles.
- Accuracy in general. n is small, the labels are not independent, and motorcycles and mopeds are in the damaged set.

## Reproduce

```
.venv/bin/python scripts/public_photo_bench.py --repeats 3   # needs ~/.config/qwen/qwen.env; ~250 calls
```

It writes a new `run-<date>.json` and never overwrites a recorded run. Script tests: `tests/test_public_photo_bench.py`.

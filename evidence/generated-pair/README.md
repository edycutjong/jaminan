# Generated pair: AI-generated test images (not photographs)

**These two images are AI-generated test images (not photographs).** No scooter was photographed. The pickup image
was made by `qwen-image-2.0`, and the return image is a `wan2.6-image` edit of it that removed both rear-view mirrors.
[`GENERATION.json`](GENERATION.json) has both prompts, the request id and the ground truth. The paths inside that file
are the builder's original file names: `pickup/p-front-left.png` is
[`pickup-front-left.png`](pickup-front-left.png) here and `return/r-front-left.png` is
[`return-front-left.png`](return-front-left.png). The copies here are resized to 1280 px wide, lossless PNG.

**What this is:** the vision model's real, recorded answers to two claims the builder pointed on this pair, through the
app's own claim path. **What it is not:** a benchmark, an accuracy number, or real-world evidence. One angle, two
claims, generated images. The bench on real scooter photos has not run, and no model is pinned
(`JAMINAN_BENCHMARKED_MODEL` is empty), so every line ends `comparison_unavailable` and nothing is charged.

| File | What it is |
|---|---|
| [`pickup-front-left.png`](pickup-front-left.png), [`return-front-left.png`](return-front-left.png) | The pair. Both pass the frame gate (pickup blur variance 259.5, return 225.0; no low-comparability tiles) |
| [`GENERATION.json`](GENERATION.json) | How the images were generated: models, prompts, request id, ground truth |
| [`run-2026-10-25.json`](run-2026-10-25.json) | The recorded run, 2026-10-24 18:22 UTC (2026-10-25 01:22 WIB, the date in the file name): per claim, the tap box, the crops' regions, 3 model calls with model id, request id, latency, raw parsed answer, the app's disposition and answer text, and `model_reading` |
| [`run-2026-10-25-1.json`](run-2026-10-25-1.json) | The first run of the same script, 47 seconds earlier. It got the same readings on all 6 calls. It is kept because its `matches_expected` flag counted "new, other class" as a match for C2, which was too loose; the flag was fixed before the second run |

Reproduce: `.venv/bin/python scripts/generated_pair.py` (needs a Qwen key). It runs the frame gate on each image, cuts
the return crop (×2) and the pickup search area (×4) around each tap exactly as `Service.claim` does, calls
`Vision.claim` on the configured model (`qwen3-vl-plus`), and runs `rules.decide_claim`. `model_reading` is what the
same rules would read from the answer if this model were pinned; it is never used to price anything.

## The two claims (pointed by the builder from the notes in `GENERATION.json`)

| Claim | The shop points at | True answer | Recorded model reading, 3 calls each | The app's answer |
|---|---|---|---|---|
| C1 | `front_fairing` / `dent`, box `[0.435, 0.425, 0.075, 0.135]`: the grey scuff | **old**: the same scuff is in the pickup image | **new since pickup** in all 3 (confidence 0.85): "the same location in the pickup photo shows no such mark". **Wrong** | comparison unavailable — nothing charged from the hold |
| C2 | `mirror` / `missing_part`, box `[0.36, 0.0, 0.36, 0.24]`: both mirror mounts | **new**: both mirrors are missing at return | a mark at return but **not a missing mirror** in all 3 (confidence 0.3): "a dark smudge on the front fairing near the headlight". **Wrong** | comparison unavailable — nothing charged from the hold |

The tariff has no `front_fairing` / `scuff` line, so C1 uses the nearest priced line on that part (`dent`, $45.00): a
shop over-claiming an old mark. Had `qwen3-vl-plus` been pinned without the bench, `rules.decide_claim` would have priced C1
at **$45.00** for a mark that was there at pickup. That is the failure the bench gate exists to stop. C2 shows a
second weakness: the claim prompt asks about a "mark" at the tap, which fits a missing part badly. The prompt was not
changed here, because tuning it on the only test pair would make the next result meaningless. Both findings feed the bench.

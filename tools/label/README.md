# Labelling tool

Local page for hand-labelling the staged photo set before any model run. Stdlib only.

```bash
python3 tools/label/serve.py --dir path/to/staged-photos   # → http://127.0.0.1:8765
```

It writes `frames.csv`, `labels.csv` and `claims.csv` next to the photos (columns in `serve.py`).
Boxes are normalized 0–1 on the photo with EXIF orientation applied — the same frame the gate and the model see.

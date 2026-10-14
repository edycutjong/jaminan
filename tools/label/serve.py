"""Hand-labelling tool for the staged photo set — local only, stdlib only.

    python3 tools/label/serve.py --dir ../assets/staged      # then open http://127.0.0.1:8765

Writes three CSVs next to the photos (labels BEFORE any model run, so the bench can't be tuned to the
model's own output):
  frames.csv  file, walkaround_id, scooter, split, phone, phase, angle, light, pairs_with, notes
  labels.csv  walkaround_id, scooter, split, phone, phase, angle, part, damage_class, new,
              bbox_x, bbox_y, bbox_w, bbox_h, notes                      (schema of specs/seed-data.md)
  claims.csv  claim_id, walkaround_id, split, angle, bbox_x, bbox_y, bbox_w, bbox_h, part, damage_class,
              expected, pickup_bbox_x, pickup_bbox_y, pickup_bbox_w, pickup_bbox_h, notes
Boxes are normalized 0–1 on the photo as displayed (EXIF orientation applied).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
COLUMNS = {
    "frames": ["file", "walkaround_id", "scooter", "split", "phone", "phase", "angle", "light", "pairs_with", "notes"],
    "labels": ["walkaround_id", "scooter", "split", "phone", "phase", "angle", "part", "damage_class", "new",
               "bbox_x", "bbox_y", "bbox_w", "bbox_h", "notes"],
    "claims": ["claim_id", "walkaround_id", "split", "angle", "bbox_x", "bbox_y", "bbox_w", "bbox_h", "part",
               "damage_class", "expected", "pickup_bbox_x", "pickup_bbox_y", "pickup_bbox_w", "pickup_bbox_h", "notes"],
}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


def make_handler(root: Path):
    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # quiet
            pass

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            if path in ("/", "/index.html"):
                return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/api/files":
                files = sorted(str(p.relative_to(root)) for p in root.rglob("*")
                               if p.suffix.lower() in IMAGE_EXT and not p.name.startswith("."))
                return self._send(200, json.dumps(files).encode())
            if path.startswith("/api/csv/"):
                name = path.rsplit("/", 1)[-1]
                f = root / f"{name}.csv"
                rows = list(csv.DictReader(f.open())) if f.exists() else []
                return self._send(200, json.dumps(rows).encode())
            if path.startswith("/img/"):
                f = (root / path[5:]).resolve()
                if root not in f.parents or not f.exists():
                    return self._send(404, b"{}")
                return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            self._send(404, b"{}")

        def do_POST(self):
            path = urlparse(self.path).path
            if not path.startswith("/api/csv/"):
                return self._send(404, b"{}")
            name = path.rsplit("/", 1)[-1]
            if name not in COLUMNS:
                return self._send(400, b'{"error":"unknown table"}')
            rows = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=COLUMNS[name], extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)
            (root / f"{name}.csv").write_text(buf.getvalue())
            self._send(200, json.dumps({"ok": True, "rows": len(rows)}).encode())

    return H


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="folder with the staged photos (kitchen: assets/staged)")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    root = Path(a.dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    print(f"labelling {root} → http://127.0.0.1:{a.port}")
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(root)).serve_forever()

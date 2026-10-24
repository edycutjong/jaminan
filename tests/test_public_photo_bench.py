"""scripts/public_photo_bench.py: what counts as a false "new", flips, the T3 class match, gate rejections, no overwrite."""
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
REAL_LABELS = ROOT / "evidence" / "public-photo-bench" / "labels.csv"


def _script():
    spec = importlib.util.spec_from_file_location("public_photo_bench", ROOT / "scripts" / "public_photo_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LABELS = """image,mark,kind,vehicle,angle,part,damage_class,x,y,w,h,note
d01,d01-m1,mark,scooter,2,side_panel,scuff,0.4,0.4,0.2,0.2,old scuff
d01,d01-m2,mark,scooter,2,mirror,missing_part,0.1,0.0,0.1,0.1,mirror gone
d02,d02-m1,mark,scooter,3,front_fairing,crack,0.5,0.5,0.1,0.1,on a frame the gate rejects
c01,c01-clean,clean_spot,scooter,2,side_panel,,0.3,0.3,0.1,0.1,clean
"""


def answer(**k):
    base = dict(mark_at_return=True, class_consistent=True, visible_at_pickup=True, pickup_comparable=True,
                same_view=True, pickup_bbox=None, closeup_located=None, confidence=0.9, rationale="")
    base.update(k)
    return SimpleNamespace(model_dump=lambda: base)


def call(parsed, ok=True, error=None):
    return SimpleNamespace(ok=ok, parsed=parsed, model="qwen3-vl-plus", error=error,
                           meta=lambda: {"model": "qwen3-vl-plus", "request_id": "rid", "ms": 1000, "error": error,
                                         "usage": None})


class FakeVision:
    """d01-m1 flips old → new on repeat 2; d01-m2 is always old; the clean spot reads no mark."""

    def __init__(self):
        self.seen = {}

    def claim(self, ret, pick, closeups, part, cls, angle):
        n = self.seen[part] = self.seen.get(part, 0) + 1
        if part == "side_panel" and cls == "scuff" and angle == 2 and n == 2:
            return call(answer(visible_at_pickup=False))
        if part == "side_panel" and angle == 2 and ret == b"c01":
            return call(answer(mark_at_return=False))
        return call(answer())

    def premark(self, jpeg, angle):
        if jpeg != b"d01":
            raise AssertionError("pre-mark asked about a frame without marks or a rejected frame")
        n = self.seen["pm"] = self.seen.get("pm", 0) + 1
        if n == 3:
            return call(None, ok=False, error="schema: bad")
        marks = [SimpleNamespace(model_dump=lambda: {"part": "side_panel", "damage_class": "dent",
                                                     "bbox": [0.45, 0.45, 0.1, 0.1], "confidence": 0.8})]
        return call(SimpleNamespace(marks=marks))


def test_scoring_flips_t3_match_and_gate_rejection(tmp_path, monkeypatch):
    pb = _script()
    (tmp_path / "photos").mkdir()
    for img in ("d01", "d02", "c01"):
        (tmp_path / "photos" / f"{img}.jpg").write_bytes(img.encode())
    (tmp_path / "labels.csv").write_text(LABELS)
    monkeypatch.setattr(pb, "DIR", tmp_path)

    def check(data):
        ok = data != b"d02"
        return SimpleNamespace(ok=ok, reason=None if ok else "blur", blur_var=99.0, glare_frac=0.0, width=900,
                               height=600, low_tiles=[], sha256="sha"), data

    monkeypatch.setattr(pb.gate, "check", check)
    monkeypatch.setattr(pb.gate, "crop", lambda jpeg, bbox, scale: (jpeg, bbox))
    s = SimpleNamespace(vision_model="qwen3-vl-plus", benchmarked_model="", confidence_floor=0.7,
                        chargeable_classes=("missing_part", "broken_part"))
    out = pb.run(FakeVision(), s, pb.load_labels(tmp_path / "labels.csv"), repeats=3, workers=1)
    t1, t2, t3 = (out["summary"][k] for k in ("t1_old_mark", "t2_clean_spot", "t3_damage_reading"))
    assert out["gate_rejected"] == ["d02"]
    assert t1["items"] == 2 and t1["calls"] == 6
    assert t1["false_new"] == 1 and t1["flipped_items"] == ["d01-m1"] and t1["pass"] is False
    assert t1["readings"] == {"old": 5, "new": 1}  # scuff is not chargeable: evidence_only still reads "new"
    assert t2 == {**t2, "items": 1, "false_new": 0, "pass": True, "readings": {"no mark": 3}}
    assert t3["confusion"] == {"scuff": {"dent": 2, "no_answer": 1}, "missing_part": {"not_found": 2, "no_answer": 1}}
    assert t3["class_agrees"] == 0 and t3["not_found"] == 2 and t3["no_answer"] == 2
    assert out["summary"]["latency_ms"] == {"calls": 12, "p50": 1000, "p95": 1000}
    assert all(r["disposition"] == "comparison_unavailable" for it in out["t1_old_mark"] for r in it["runs"])
    json.dumps(out)  # the record is JSON-serialisable


def test_helpers():
    pb = _script()
    assert pb.percentile([], 50) is None
    assert pb.percentile([5, 1, 3, 2, 4], 50) == 3 and pb.percentile(list(range(1, 101)), 95) == 95
    assert pb.best_overlap([0.0, 0.0, 0.1, 0.1], [{"bbox": [0.5, 0.5, 0.1, 0.1]}]) is None
    big = {"bbox": [0.0, 0.0, 1.0, 1.0]}
    assert pb.best_overlap([0.4, 0.4, 0.1, 0.1], [{"bbox": [0.45, 0.45, 0.2, 0.2]}, big]) is big


def test_labels_commit_and_real_labels():
    pb = _script()
    rows = pb.load_labels(REAL_LABELS)
    assert {r["kind"] for r in rows} == {"mark", "clean_spot"}
    assert all(0 <= v <= 1 for r in rows for v in r["bbox"]) and all(1 <= r["angle"] <= 8 for r in rows)
    assert pb.labels_commit(Path("/nonexistent/labels.csv")) is None


def test_main_never_overwrites_a_recorded_run(tmp_path, monkeypatch):
    pb = _script()
    recorded = tmp_path / f"run-{datetime.now():%Y-%m-%d}.json"
    recorded.write_text('{"kept": true}\n')
    monkeypatch.setattr(pb, "DIR", tmp_path)
    monkeypatch.setattr(pb, "ROOT", tmp_path)
    monkeypatch.setattr(pb, "load_local_env", lambda: None)
    monkeypatch.setattr(pb, "from_settings", lambda s: None)
    monkeypatch.setattr(pb, "load_labels", lambda p: [])
    monkeypatch.setattr(pb, "run", lambda *a: {"summary": {"ok": 1}})
    monkeypatch.setattr("sys.argv", ["public_photo_bench.py", "--repeats", "1"])
    pb.main()
    assert recorded.read_text() == '{"kept": true}\n'
    assert json.loads((tmp_path / f"run-{datetime.now():%Y-%m-%d}-1.json").read_text()) == {"summary": {"ok": 1}}

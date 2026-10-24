"""scripts/generated_pair.py: a frame the gate rejects is never compared, and a recorded run is never overwritten."""
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("generated_pair", ROOT / "scripts" / "generated_pair.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class NoVision:
    def claim(self, *a, **k):
        raise AssertionError("the model was asked about a frame the gate rejected")


def test_a_rejected_frame_is_recorded_with_no_model_call_and_overwrites_nothing(tmp_path, monkeypatch):
    gp = _script()
    for name in gp.FRAMES.values():
        (tmp_path / name).write_bytes(b"frame")
    recorded = tmp_path / f"run-{datetime.now():%Y-%m-%d}.json"
    recorded.write_text('{"kept": true}\n')
    verdict = {"pickup-front-left.png": True, "return-front-left.png": False}
    files = iter(gp.FRAMES.values())

    def check(data):
        ok = verdict[next(files)]
        return SimpleNamespace(ok=ok, reason=None if ok else "blur", blur_var=12.0, glare_frac=0.0, width=1280,
                               height=853, low_tiles=[], sha256="sha"), b"jpeg"

    monkeypatch.setattr(gp, "DIR", tmp_path)
    monkeypatch.setattr(gp, "ROOT", tmp_path)
    monkeypatch.setattr(gp, "load_local_env", lambda: None)
    monkeypatch.setattr(gp, "from_settings", lambda s: NoVision())
    monkeypatch.setattr(gp.gate, "check", check)
    monkeypatch.setattr("sys.argv", ["generated_pair.py", "--repeats", "1"])
    with pytest.raises(SystemExit, match="rejected the return frame"):
        gp.main()
    assert recorded.read_text() == '{"kept": true}\n'
    out = json.loads(recorded.with_name(recorded.stem + "-1.json").read_text())
    assert out["claims"] == [] and out["frames"]["return"]["gate"]["ok"] is False and "no claim was compared" in out["stopped"]

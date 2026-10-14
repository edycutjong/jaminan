"""Frame gate on synthetic test patterns (contract tests of the arithmetic, not a calibration)."""
import io

import numpy as np
from PIL import Image, ImageFilter

from jaminan import gate


def jpeg(arr):
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(buf, "JPEG", quality=92)
    return buf.getvalue()


rng = np.random.default_rng(7)
SHARP = rng.integers(40, 200, size=(960, 1280, 3))


def test_sharp_frame_passes_and_is_normalized_to_1280_and_150kb():
    res, out = gate.check(jpeg(SHARP))
    assert res.ok and res.width == 1280 and len(out) <= gate.MAX_JPEG_BYTES
    assert len(res.sha256) == 64


def test_blurred_frame_is_rejected_before_any_model_call():
    img = Image.fromarray(SHARP.astype(np.uint8)).filter(ImageFilter.GaussianBlur(12))
    buf = io.BytesIO(); img.save(buf, "JPEG")
    res, _ = gate.check(buf.getvalue())
    assert not res.ok and res.reason == "blurry"


def test_glared_frame_is_rejected():
    arr = SHARP.copy(); arr[:, :700] = 255
    res, _ = gate.check(jpeg(arr))
    assert not res.ok and res.reason == "glare"


def test_local_glare_patch_passes_the_frame_but_flags_its_tiles():
    arr = SHARP.copy(); arr[240:480, 320:640] = 255     # one tile of a 4x4 grid
    res, _ = gate.check(jpeg(arr))
    assert res.ok
    assert [0.25, 0.25, 0.25, 0.25] in res.low_tiles


def test_small_frames_are_resized_to_the_fixed_width_first():
    res, _ = gate.check(jpeg(rng.integers(40, 200, size=(240, 320, 3))))
    assert res.width == 1280 and res.height == 960


def test_crop_and_map_back_round_trip():
    _, out = gate.check(jpeg(SHARP))
    c, region = gate.crop(out, [0.4, 0.4, 0.1, 0.1], scale=2.0)
    assert Image.open(io.BytesIO(c)).width > 0
    assert abs(region[2] - 0.2) < 0.02
    full = gate.map_back([0.25, 0.25, 0.5, 0.5], region)
    assert abs(full[0] - (region[0] + 0.25 * region[2])) < 1e-3

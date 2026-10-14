"""Contract tests on the model I/O: schema parsing, box normalization, failure → no answer.
No accuracy is claimed here — the accuracy bench runs on the staged photo set."""
import json

import httpx
import pytest
import respx

from jaminan import vision
from jaminan.vision import ClaimAnswer, MarkList, Vision

BASE = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


def reply(content, model="qwen3-vl-plus", status=200):
    return httpx.Response(status, json={"id": "req-1", "model": model,
                                        "choices": [{"message": {"content": content}}], "usage": {"total_tokens": 9}})


GOOD = {"mark_at_return": True, "class_consistent": True, "visible_at_pickup": False, "pickup_comparable": True,
        "same_view": True, "pickup_bbox": [400, 380, 120, 90], "closeup_located": None, "confidence": 0.91,
        "rationale": "crack on the mirror housing is not in the pickup photo"}


def v():
    return Vision(BASE, "k", "qwen3-vl-plus")


@respx.mock
def test_claim_answer_parses_and_normalizes_the_0_1000_grid():
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=reply(json.dumps(GOOD)))
    c = v().claim(b"r", b"p", [], "mirror_housing", "crack", 2)
    assert c.ok and c.model == "qwen3-vl-plus" and c.request_id == "req-1"
    assert c.parsed.pickup_bbox == [0.4, 0.38, 0.12, 0.09]
    sent = json.loads(route.calls[0].request.content)
    assert sent["response_format"]["type"] == "json_schema" and sent["temperature"] == 0
    assert "price" not in json.dumps(sent).lower().replace("never estimate prices", "")  # I1: no prices sent
    assert route.calls[0].request.headers["User-Agent"].startswith("jaminan/")


@respx.mock
def test_array_wrapped_answer_is_unwrapped():
    respx.post(f"{BASE}/chat/completions").mock(return_value=reply(json.dumps([GOOD]), model="qwen3.8-max"))
    c = v().claim(b"r", b"p", [], "mirror_housing", "crack", 2)
    assert c.ok and c.model == "qwen3.8-max"


@pytest.mark.parametrize("content", ["not json", json.dumps({**GOOD, "same_view": "maybe"}),
                                     json.dumps({k: v for k, v in GOOD.items() if k != "mark_at_return"}),
                                     json.dumps({**GOOD, "confidence": 3})])
@respx.mock
def test_schema_failures_yield_no_answer(content):
    respx.post(f"{BASE}/chat/completions").mock(return_value=reply(content))
    c = v().claim(b"r", b"p", [], "mirror_housing", "crack", 2)
    assert not c.ok and c.parsed is None and c.error.startswith("schema")


@respx.mock
def test_http_error_and_timeout_yield_no_answer():
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(429, json={"error": {"code": "Throttling"}}))
    assert not v().claim(b"r", b"p", [], "side_panel", "dent", 3).ok
    respx.post(f"{BASE}/chat/completions").mock(side_effect=httpx.ReadTimeout("slow"))
    c = v().claim(b"r", b"p", [], "side_panel", "dent", 3)
    assert not c.ok and "timeout" in c.error


def test_mark_list_rejects_unknown_classes_and_maps_unknown_parts():
    with pytest.raises(Exception):
        MarkList.model_validate({"marks": [{"part": "mirror", "damage_class": "rust", "bbox": [1, 2, 3, 4]}]})
    m = MarkList.model_validate({"marks": [{"part": "spoiler", "damage_class": "dent", "bbox": [100, 100, 50, 50],
                                            "confidence": .8}]})
    assert m.marks[0].part == "other" and m.marks[0].bbox == [0.1, 0.1, 0.05, 0.05]


def test_claim_schema_has_exactly_the_published_fields():
    assert set(vision.SCHEMAS["claim"]["required"]) == set(ClaimAnswer.model_fields)


@pytest.mark.live_model
def test_live_qwen_returns_a_schema_valid_claim_answer():
    """Contract only (synthetic pattern, not a scooter): the live API answers in the claim schema."""
    import io
    import os
    from PIL import Image, ImageDraw
    from jaminan.config import load_local_env
    load_local_env()
    if not os.environ.get("QWEN_API_KEY"):
        pytest.skip("no Qwen key")
    def pic(mark):
        im = Image.new("RGB", (384, 384), (190, 190, 185)); d = ImageDraw.Draw(im)
        if mark: d.line((150, 150, 240, 230), fill=(30, 30, 30), width=6)
        b = io.BytesIO(); im.save(b, "JPEG"); return b.getvalue()
    c = Vision(os.environ["QWEN_BASE_URL"], os.environ["QWEN_API_KEY"], "qwen3-vl-plus").claim(
        pic(True), pic(False), [], "side_panel", "scuff", 3)
    assert c.ok, c.error
    assert isinstance(c.parsed, ClaimAnswer) and c.model

"""Vision client branches: every job's request shape, the failure shapes, and the box normaliser."""
import json

import httpx
import pytest
import respx

from jaminan import config, vision
from jaminan.vision import CloseupLocation, Vision

BASE = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


def reply(content, status=200, **msg):
    return httpx.Response(status, json={"id": "req-9", "model": "qwen3.8-max",
                                        "choices": [{"message": {"content": content, **msg}}]})


@pytest.mark.parametrize("bad", [[0.1, 0.2], "box", [1, 2, 3, 4, 5]])
def test_a_box_that_is_not_four_numbers_is_rejected(bad):
    with pytest.raises(ValueError):
        CloseupLocation(located=True, bbox=bad)


def test_a_missing_box_stays_missing_and_corner_boxes_are_scaled_from_a_1000_grid():
    assert CloseupLocation(located=False, bbox=None).bbox is None
    assert CloseupLocation(located=True, bbox=[100, 200, 300, 400]).bbox == [0.1, 0.2, 0.2, 0.2]
    assert CloseupLocation(located=True, bbox=[300, 400, 100, 200]).bbox == [0.1, 0.2, 0.2, 0.2]  # corners swapped


def test_the_recorded_c1_box_is_read_as_corners_on_the_pointed_scuff():
    """qwen3-vl-plus's pickup box for C1 in all 6 recorded calls was [380, 380, 580, >=620] on the pickup search area,
    whose centre (500, 500) is the builder's tap. As corners it is a 200 x 240 box around that centre."""
    x, y, w, h = CloseupLocation(located=True, bbox=[380, 380, 580, 620]).bbox
    assert (x, y, w, h) == (0.38, 0.38, 0.2, 0.24) and x < 0.5 < x + w and y < 0.5 < y + h


@respx.mock
def test_each_job_sends_its_own_prompt_and_schema_and_parses_its_answer():
    route = respx.post(f"{BASE}/chat/completions")
    v = Vision(BASE, "k", "qwen3.8-max")
    img = b"\xff\xd8jpeg"
    route.mock(return_value=reply(json.dumps({"marks": []})))
    assert v.suggest(img, img, 3, [{"part": "mirror_housing", "damage_class": "crack"}]).ok
    assert v.suggest(img, img, 3, []).ok
    assert v.premark(img, 4).ok
    body = json.loads(route.calls[0].request.content)
    assert body["enable_thinking"] is False and body["response_format"]["type"] == "json_schema"
    assert "mirror_housing/crack" in body["messages"][1]["content"][-1]["text"]
    assert "none" in json.loads(route.calls[1].request.content)["messages"][1]["content"][-1]["text"]
    route.mock(return_value=reply(json.dumps({"located": True, "bbox": [0.1, 0.1, 0.2, 0.2], "confidence": 0.8})))
    assert v.locate_closeup(img, img, 2).parsed.located is True
    route.mock(return_value=reply(json.dumps({"plate": "B 1234 XYZ", "confidence": 0.9})))
    t = v.read_ticket(img, ["no_helmet", "no_licence"])
    assert t.ok and t.parsed.plate == "B 1234 XYZ"
    last = json.loads(route.calls[-1].request.content)
    assert last["response_format"] == {"type": "json_object"} and "no_helmet, no_licence" in last["messages"][1]["content"][-1]["text"]


@respx.mock
def test_a_non_qwen_max_model_does_not_get_the_thinking_switch():
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=reply(json.dumps({"plate": None})))
    Vision(BASE, "k", "qwen3-vl-plus").read_ticket(b"x", [])
    assert "enable_thinking" not in json.loads(route.calls[0].request.content)


@respx.mock
def test_a_200_with_a_non_json_body_is_no_answer():
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(200, content=b"<html>gateway</html>"))
    c = Vision(BASE, "k", "qwen3-vl-plus").read_ticket(b"x", [])
    assert not c.ok and c.parsed is None and "non-JSON" in c.error


@respx.mock
def test_a_model_refusal_is_no_answer_not_a_guess():
    respx.post(f"{BASE}/chat/completions").mock(return_value=reply("", refusal="cannot help"))
    c = Vision(BASE, "k", "qwen3-vl-plus").read_ticket(b"x", [])
    assert not c.ok and c.error == "refusal"


def test_from_settings_reads_the_qwen_fields():
    v = vision.from_settings(config.Settings(qwen_key="key", qwen_base="https://q.example/v1", vision_model="m"))
    assert (v.base, v.model) == ("https://q.example/v1", "m")

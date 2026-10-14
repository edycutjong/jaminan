"""Vision service on Qwen (DashScope international, OpenAI-compatible chat completions).

The model answers narrow yes/no questions in a scooter's part vocabulary; it never sees a price and
never returns an amount (I1). Every answer records the model id PayPal-style: the `model` field of
the response is the serving model, and only the benchmarked id can make a line chargeable.
Boxes travel as Qwen's native 0–1000 integer grid and are normalized to 0–1 here.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

PARTS = ("mirror", "mirror_housing", "indicator_lens", "front_fairing", "side_panel", "rear_panel", "seat",
         "headlight", "tail_light", "front_fender", "rear_fender", "footboard", "handlebar", "wheel", "exhaust",
         "other")
CLASSES = ("missing_part", "broken_part", "crack", "dent", "scuff")
ANGLES = {1: "front", 2: "front-left three-quarter", 3: "left side", 4: "rear-left three-quarter", 5: "rear",
          6: "rear-right three-quarter", 7: "right side", 8: "front-right three-quarter"}


def _box(v: Any) -> list[float] | None:
    if v is None:
        return None
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        raise ValueError("bbox must be [x, y, w, h]")
    nums = [float(x) for x in v]
    scale = 1000.0 if max(nums) > 1.5 else 1.0
    x, y, w, h = [min(max(n / scale, 0.0), 1.0) for n in nums]
    return [round(x, 4), round(y, 4), round(min(w, 1 - x), 4), round(min(h, 1 - y), 4)]


class ClaimAnswer(BaseModel):
    mark_at_return: bool
    class_consistent: bool
    visible_at_pickup: bool
    pickup_comparable: bool
    same_view: bool
    pickup_bbox: list[float] | None = None
    closeup_located: bool | None = None
    confidence: float = Field(ge=0, le=1)
    rationale: str = ""

    _norm = field_validator("pickup_bbox", mode="before")(classmethod(lambda cls, v: _box(v)))


class Mark(BaseModel):
    part: str
    damage_class: str
    bbox: list[float]
    confidence: float = Field(default=0.5, ge=0, le=1)

    _norm = field_validator("bbox", mode="before")(classmethod(lambda cls, v: _box(v)))

    @field_validator("damage_class")
    @classmethod
    def _cls(cls, v: str) -> str:
        if v not in CLASSES:
            raise ValueError(f"damage_class must be one of {CLASSES}")
        return v

    @field_validator("part")
    @classmethod
    def _part(cls, v: str) -> str:
        return v if v in PARTS else "other"


class MarkList(BaseModel):
    marks: list[Mark] = []


class CloseupLocation(BaseModel):
    located: bool
    bbox: list[float] | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)

    _norm = field_validator("bbox", mode="before")(classmethod(lambda cls, v: _box(v)))


class TicketRead(BaseModel):
    plate: str | None = None
    time: str | None = None           # ISO 8601 with offset, as printed
    violation: str | None = None      # one key of the closed list, or null
    amount_idr: int | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)


BOX = {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4}
SCHEMAS = {
    "claim": {"type": "object", "additionalProperties": False,
              "required": ["mark_at_return", "class_consistent", "visible_at_pickup", "pickup_comparable",
                           "same_view", "pickup_bbox", "closeup_located", "confidence", "rationale"],
              "properties": {"mark_at_return": {"type": "boolean"}, "class_consistent": {"type": "boolean"},
                             "visible_at_pickup": {"type": "boolean"}, "pickup_comparable": {"type": "boolean"},
                             "same_view": {"type": "boolean"}, "pickup_bbox": {"anyOf": [BOX, {"type": "null"}]},
                             "closeup_located": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
                             "confidence": {"type": "number"}, "rationale": {"type": "string"}}},
    "marks": {"type": "object", "additionalProperties": False, "required": ["marks"],
              "properties": {"marks": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False,
                  "required": ["part", "damage_class", "bbox", "confidence"],
                  "properties": {"part": {"type": "string", "enum": list(PARTS)},
                                 "damage_class": {"type": "string", "enum": list(CLASSES)},
                                 "bbox": BOX, "confidence": {"type": "number"}}}}}},
    "closeup": {"type": "object", "additionalProperties": False, "required": ["located", "bbox", "confidence"],
                "properties": {"located": {"type": "boolean"}, "bbox": {"anyOf": [BOX, {"type": "null"}]},
                               "confidence": {"type": "number"}}},
}

SYSTEM = (
    "You inspect photos of a rental scooter for a deposit settlement between a renter and a shop. "
    "You only answer the question asked, as JSON. You never estimate prices or amounts. "
    "Boxes are [x, y, w, h] on a 0-1000 integer grid of the image they refer to. "
    "Ignore reflections, shadows, dirt, water drops and lighting changes: they are not damage. "
    "When unsure, say so with a low confidence rather than guessing."
)

CLAIM_PROMPT = """The shop points at a mark on the RETURN photo and wants to charge it as: part = {part}, damage class = {cls}.
Image 1 = RETURN crop around the shop's tap (the tap box is the centre half of this crop).
Image 2 = PICKUP search area: the same region of the same angle ({angle}), photographed at pickup, about twice as large.
{closeup_line}
Answer:
- same_view: do images 1 and 2 show the same part of the scooter from roughly the same viewpoint?
- mark_at_return: is there a real mark (damage, not a reflection or dirt) at the tap in image 1?
- class_consistent: does that mark look like a {cls} on the {part}?
- visible_at_pickup: is the SAME mark already visible in image 2 (or in the renter's close-up)?
- pickup_comparable: is image 2 sharp, unglared and unoccluded enough at that spot to tell?
- pickup_bbox: where that same spot is in image 2 (0-1000 grid of image 2), or null if you cannot find it.
- closeup_located: if a close-up was given, does it show this same spot? else null.
- confidence: 0-1 in your whole answer. rationale: one short sentence."""

SUGGEST_PROMPT = """Image 1 = PICKUP photo, image 2 = RETURN photo, same scooter, angle: {angle}.
Marks already confirmed in the shared baseline for this angle (do NOT report these): {baseline}.
List only damage that is clearly NEW in image 2 compared with image 1 — a missing part, a broken part, a crack,
a dent or a scuff. Boxes on the 0-1000 grid of image 2. If nothing is clearly new, return an empty list."""

PREMARK_PROMPT = """This is a PICKUP photo of a rental scooter, angle: {angle}. List every visible existing damage
(missing_part, broken_part, crack, dent, scuff) with its part and a box on the 0-1000 grid. Recall matters more
than precision here: the renter reviews this list. If there is none, return an empty list."""

CLOSEUP_PROMPT = """Image 1 = a full PICKUP photo of a scooter (angle: {angle}). Image 2 = the renter's close-up of an
existing mark. Is the close-up of a spot on THIS scooter in image 1? If yes, give its box on image 1 (0-1000 grid)."""

TICKET_PROMPT = """This is a photographed Indonesian e-TLE traffic ticket (surat konfirmasi). Read: the vehicle plate
(nomor polisi), the violation time as ISO 8601 with +07:00 offset, the fine amount in IDR if printed, and the violated
article. The article MUST be one key from this closed list or null: {keys}. Return JSON
{{"plate": str|null, "time": str|null, "violation": str|null, "amount_idr": int|null, "confidence": 0-1}}."""


@dataclass
class Call:
    ok: bool
    parsed: Any
    model: str | None
    request_id: str | None
    ms: int
    error: str | None = None
    usage: dict | None = None

    def meta(self) -> dict:
        return {"model": self.model, "request_id": self.request_id, "ms": self.ms, "error": self.error,
                "usage": self.usage}


def data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


class Vision:
    def __init__(self, base: str, key: str, model: str, timeout: float = 45.0):
        self.base, self.key, self.model = base.rstrip("/"), key, model
        self.http = httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {key}",
                                                           "User-Agent": "jaminan/0.1 (+vision)"})

    def ask(self, prompt: str, images: list[bytes], schema_name: str | None, parse, max_tokens: int = 600) -> Call:
        content: list[dict] = [{"type": "image_url", "image_url": {"url": data_url(b)}} for b in images]
        content.append({"type": "text", "text": prompt})
        body: dict[str, Any] = {"model": self.model, "temperature": 0, "max_tokens": max_tokens,
                                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]}
        if schema_name:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": schema_name, "schema": SCHEMAS[schema_name], "strict": True}}
        else:
            body["response_format"] = {"type": "json_object"}
        if self.model.startswith("qwen3.8-max"):
            body["enable_thinking"] = False
        t0 = time.perf_counter()
        try:
            r = self.http.post(f"{self.base}/chat/completions", json=body)
        except httpx.HTTPError as e:
            return Call(False, None, None, None, int((time.perf_counter() - t0) * 1000), f"timeout/transport: {e}")
        ms = int((time.perf_counter() - t0) * 1000)
        try:
            j = r.json()
        except ValueError:
            return Call(False, None, None, None, ms, f"http {r.status_code}: non-JSON body")
        if r.status_code != 200:
            return Call(False, None, j.get("model"), j.get("id") or j.get("request_id"), ms,
                        f"http {r.status_code}: {(j.get('error') or {}).get('code') or j.get('code')}")
        msg = (j.get("choices") or [{}])[0].get("message") or {}
        text = msg.get("content") or ""
        if msg.get("refusal"):
            return Call(False, None, j.get("model"), j.get("id"), ms, "refusal", j.get("usage"))
        try:
            raw = json.loads(text)
            if isinstance(raw, list) and raw:  # some models wrap the object in an array
                raw = raw[0]
            parsed = parse(raw)
        except (ValueError, ValidationError, TypeError) as e:
            return Call(False, None, j.get("model"), j.get("id"), ms, f"schema: {str(e)[:200]}", j.get("usage"))
        return Call(True, parsed, j.get("model"), j.get("id"), ms, None, j.get("usage"))

    # -- the jobs ----------------------------------------------------------------------------------
    def claim(self, return_crop: bytes, pickup_area: bytes, closeups: list[bytes], part: str, damage_class: str,
              angle: int) -> Call:
        closeup_line = ("Image 3 = the renter's own close-up of an existing mark near this spot, taken at pickup."
                        if closeups else "No renter close-up was taken for this spot.")
        prompt = CLAIM_PROMPT.format(part=part.replace("_", " "), cls=damage_class.replace("_", " "),
                                     angle=ANGLES.get(angle, angle), closeup_line=closeup_line)
        return self.ask(prompt, [return_crop, pickup_area, *closeups[:1]], "claim", ClaimAnswer.model_validate)

    def suggest(self, pickup: bytes, ret: bytes, angle: int, baseline: list[dict]) -> Call:
        desc = [f"{m['part']}/{m['damage_class']}" for m in baseline] or "none"
        return self.ask(SUGGEST_PROMPT.format(angle=ANGLES.get(angle, angle), baseline=desc), [pickup, ret], "marks",
                        MarkList.model_validate)

    def premark(self, pickup: bytes, angle: int) -> Call:
        return self.ask(PREMARK_PROMPT.format(angle=ANGLES.get(angle, angle)), [pickup], "marks", MarkList.model_validate)

    def locate_closeup(self, frame: bytes, closeup: bytes, angle: int) -> Call:
        return self.ask(CLOSEUP_PROMPT.format(angle=ANGLES.get(angle, angle)), [frame, closeup], "closeup",
                        CloseupLocation.model_validate)

    def read_ticket(self, image: bytes, keys: list[str]) -> Call:
        return self.ask(TICKET_PROMPT.format(keys=", ".join(keys)), [image], None, TicketRead.model_validate)


def from_settings(s) -> Vision:
    return Vision(s.qwen_base, s.qwen_key, s.vision_model)

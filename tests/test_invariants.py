"""The two decisions that must never be wrong, checked across their whole input space (no network).

1. decide_claim: a line is chargeable only when every condition for "new since pickup" holds.
2. settle_plan: the hold never pays a line the renter did not accept, and never exceeds the authorization.
"""
import itertools

from hypothesis import given, settings
from hypothesis import strategies as st

from jaminan import rules, tariff
from jaminan.rules import SettleBlocked, decide_claim, settle_plan

T = tariff.load("tv1")
BENCH = "bench-pinned"
FLOOR = 0.7
CLASSES = ("crack", "dent", "scuff", "missing_part", "broken_part")
ENABLED = ("crack", "dent", "missing_part", "broken_part")  # scuff stays evidence-only until the bench enables it
BASE_MARK = {"confirmed": True, "angle": 2, "part": "mirror_housing", "damage_class": "crack", "bbox": [0.38, 0.38, 0.2, 0.2]}
LOW_TILE = [0.35, 0.35, 0.3, 0.3]
TAP = [0.40, 0.40, 0.10, 0.10]
# rear_panel/scuff is priced in the tariff but not enabled; mirror_housing/dent is enabled but has no tariff line
PARTS = ("mirror_housing", "front_fairing", "rear_panel")


def _cases():
    bools = (True, False)
    for part, cls in itertools.product(PARTS, CLASSES):
        for flags in itertools.product(bools, repeat=5):
            for model, conf, marked, low in itertools.product((BENCH, "other-model", None), (None, 0.3, 0.7, 0.95), bools, bools):
                answer = dict(zip(rules.CLAIM_FIELDS, flags, strict=True), confidence=conf, pickup_bbox=None)
                yield part, cls, answer, model, marked, low


def _decide(part, cls, answer, model, marked, low):
    return decide_claim(
        answer=answer, serving_model=model, benchmarked_model=BENCH, part=part, damage_class=cls, angle=2,
        tap_bbox=TAP, price_cents=T.price(part, cls), baseline_marks=[BASE_MARK] if marked else [],
        pickup_low_tiles=[LOW_TILE] if low else [], chargeable_classes=ENABLED, confidence_floor=FLOOR)


def test_no_input_ever_charges_a_mark_that_the_baseline_or_the_gate_can_explain():
    n = chargeable = 0
    for case in _cases():
        part, cls, answer, model, marked, low = case
        d = _decide(*case)
        n += 1
        if d.disposition != "chargeable":
            assert d.price_cents is None
            continue
        chargeable += 1
        assert model == BENCH, "only the benchmarked model can produce a chargeable line"
        assert answer["same_view"] and answer["mark_at_return"] and answer["pickup_comparable"] and answer["class_consistent"]
        assert not answer["visible_at_pickup"], "a mark visible at pickup is never chargeable"
        assert not low, "a spot in a low-comparability tile is never chargeable"
        assert not (marked and part == BASE_MARK["part"] and cls == BASE_MARK["damage_class"]), "I3: confirmed baseline mark"
        assert answer["confidence"] is not None and answer["confidence"] >= FLOOR
        assert cls in ENABLED
        assert d.price_cents is not None and d.price_cents == T.price(part, cls), "I1: priced from the tariff, never from the model"
    assert n == len(PARTS) * len(CLASSES) * 32 * 3 * 4 * 2 * 2 == 23040
    assert chargeable > 0


_line = st.fixed_dictionaries({
    "part": st.sampled_from(("mirror_housing", "front_fairing", "side_panel", "rear_panel")),
    "damage_class": st.sampled_from(("crack", "dent", "scuff")),
    "disposition": st.sampled_from(("chargeable", "excluded_baseline", "evidence_only", "not_comparable", "no_mark")),
    "renter_decision": st.sampled_from((None, "accepted", "contested")),
    "tampered": st.sampled_from((False,) * 9 + (True,)),
})


def _materialise(i, spec):
    price = T.price(spec["part"], spec["damage_class"])
    stored = None if spec["disposition"] != "chargeable" or price is None else price + (1 if spec["tampered"] else 0)
    return {"id": f"L{i}", "part": spec["part"], "damage_class": spec["damage_class"], "disposition": spec["disposition"],
            "price_cents": stored, "renter_decision": spec["renter_decision"]}


@settings(max_examples=3000, deadline=None)
@given(specs=st.lists(_line, max_size=6), deposit=st.integers(0, 30000), fee=st.integers(0, 5000), force=st.booleans())
def test_the_hold_pays_exactly_the_accepted_chargeable_lines_and_blocks_exactly_when_it_should(specs, deposit, fee, force):
    lines = [_materialise(i, s) for i, s in enumerate(specs)]
    chargeable = [ln for ln in lines if ln["disposition"] == "chargeable"]
    decided = [ln for ln in chargeable if ln["renter_decision"] in ("accepted", "contested")]
    undecided = [ln for ln in chargeable if ln not in decided]
    bad_price = [ln for ln in decided if T.price(ln["part"], ln["damage_class"]) != ln["price_cents"]
                 or ln["price_cents"] is None]
    should_block = bool(bad_price) or (bool(undecided) and not force)
    try:
        p = settle_plan(fee_cents=fee, deposit_cents=deposit, authorized_cents=fee + deposit, fee_captured_cents=fee,
                        lines=lines, tariff_price=T.price, force=force)
    except SettleBlocked:
        assert should_block, "settle blocked although every chargeable line was answered at its tariff price"
        return
    assert not should_block, "settle went through with an unanswered line or a price that is not the tariff's (I1)"
    accepted_ids = {ln["id"] for ln in decided if ln["renter_decision"] == "accepted"}
    assert {ln["id"] for ln in p.accepted} == accepted_ids, "exactly the accepted chargeable lines are paid"
    paid = sum(T.price(ln["part"], ln["damage_class"]) for ln in p.accepted)
    assert p.capture_cents == min(paid, deposit)
    assert p.void == (p.capture_cents == 0)
    contested_ids = {ln["id"] for ln in decided if ln["renter_decision"] == "contested"}
    invoiced = {i["line_id"] for i in p.invoice_items if i["kind"] == "contested"}
    assert invoiced == contested_ids, "only contested lines are invoiced; unanswered lines never are"
    assert p.invoice_cents == max(paid - deposit, 0) + sum(T.price(ln["part"], ln["damage_class"]) for ln in decided
                                                           if ln["id"] in contested_ids)


def test_settle_property_inputs_include_clean_returns_and_real_captures():
    """The property test above must not be vacuous: a plain accepted line goes through and captures."""
    line = {"id": "L0", "part": "front_fairing", "damage_class": "dent", "disposition": "chargeable",
            "price_cents": 4500, "renter_decision": "accepted"}
    p = settle_plan(fee_cents=1500, deposit_cents=10000, authorized_cents=11500, fee_captured_cents=1500,
                    lines=[line], tariff_price=T.price)
    assert p.capture_cents == 4500 and not p.void

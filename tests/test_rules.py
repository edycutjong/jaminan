"""Money rules and the claim disposition order — every path, no network."""
import pytest

from jaminan import rules, tariff
from jaminan.rules import IllegalTransition, SettleBlocked, check_transition, decide_claim, settle_plan

T = tariff.load("tv1")
BENCH = "qwen-bench-pinned"
NEW = {"mark_at_return": True, "class_consistent": True, "visible_at_pickup": False, "pickup_comparable": True,
       "same_view": True, "confidence": 0.93, "pickup_bbox": None}


def decide(answer=NEW, model=BENCH, part="mirror_housing", cls="crack", marks=(), low=(), classes=None,
           floor=0.7, bbox=(0.40, 0.40, 0.10, 0.10), angle=2):
    return decide_claim(answer=answer, serving_model=model, benchmarked_model=BENCH, part=part, damage_class=cls,
                        angle=angle, tap_bbox=list(bbox), price_cents=T.price(part, cls), baseline_marks=list(marks),
                        pickup_low_tiles=list(low), confidence_floor=floor,
                        chargeable_classes=classes or ("missing_part", "broken_part", "crack", "dent"))


# --- disposition order -----------------------------------------------------------------------
def test_clearly_new_mark_is_priced_from_the_tariff_only():
    d = decide()
    assert d.disposition == "chargeable" and d.price_cents == 1800


def test_answer_never_carries_a_price_into_the_line():
    d = decide(answer={**NEW, "price_cents": 99999, "amount": 500})
    assert d.price_cents == T.price("mirror_housing", "crack")  # I1


@pytest.mark.parametrize("answer,model,expected", [
    (None, BENCH, "comparison_unavailable"),
    (NEW, "qwen3.8-max", "comparison_unavailable"),
    (NEW, None, "comparison_unavailable"),
    ({**NEW, "same_view": "yes"}, BENCH, "comparison_unavailable"),
    ({**NEW, "same_view": False}, BENCH, "retake"),
    ({**NEW, "mark_at_return": False}, BENCH, "no_mark"),
    ({**NEW, "visible_at_pickup": True}, BENCH, "excluded_baseline"),
    ({**NEW, "pickup_comparable": False}, BENCH, "not_comparable"),
    ({**NEW, "class_consistent": False}, BENCH, "class_mismatch"),
    ({**NEW, "confidence": 0.4}, BENCH, "evidence_only"),
    ({**NEW, "confidence": None}, BENCH, "evidence_only"),
])
def test_disposition_order(answer, model, expected):
    assert decide(answer=answer, model=model).disposition == expected


def test_no_benchmarked_model_pinned_means_nothing_is_chargeable():
    d = decide_claim(answer=NEW, serving_model="qwen3-vl-plus", benchmarked_model="", part="mirror_housing",
                     damage_class="crack", angle=2, tap_bbox=[.4, .4, .1, .1], price_cents=1800, baseline_marks=[],
                     pickup_low_tiles=[], chargeable_classes=("crack",), confidence_floor=0.7)
    assert d.disposition == "comparison_unavailable"


def test_retake_beats_no_mark_and_no_mark_beats_baseline():
    assert decide(answer={**NEW, "same_view": False, "mark_at_return": False}).disposition == "retake"
    assert decide(answer={**NEW, "mark_at_return": False, "visible_at_pickup": True}).disposition == "no_mark"


def test_scuff_is_evidence_only_until_the_bench_enables_it():
    assert decide(part="side_panel", cls="scuff").disposition == "evidence_only"
    assert decide(part="side_panel", cls="scuff", classes=("scuff",)).disposition == "chargeable"


def test_class_with_no_tariff_line_is_never_priced():
    assert decide(part="seat", cls="crack").disposition == "evidence_only"


def test_low_comparability_boundary_is_half_the_tap_box():
    box = (0.5, 0.5, 0.25, 0.25)   # binary fractions: the overlap is exactly representable
    assert decide(bbox=box, low=[[0.5, 0.5, 0.125, 0.25]]).disposition == "not_comparable"   # exactly 50% of the box
    assert decide(bbox=box, low=[[0.5, 0.5, 0.1171875, 0.25]]).disposition == "chargeable"   # 46.9%


def test_a_baseline_mark_of_another_part_or_class_does_not_exclude_the_tap():
    mark = {"confirmed": True, "angle": 2, "part": "mirror_housing", "damage_class": "crack", "bbox": [0.40, 0.40, 0.10, 0.10]}
    assert decide(part="front_fairing", cls="dent", marks=[mark]).disposition == "chargeable"
    assert decide(part="mirror_housing", cls="dent", marks=[{**mark, "damage_class": "crack"}]).disposition != "excluded_baseline"
    assert decide(part="mirror_housing", cls="crack", marks=[mark]).disposition == "excluded_baseline"


def test_confidence_exactly_at_the_floor_is_enough_and_just_under_is_not():
    assert decide(answer={**NEW, "confidence": 0.7}, floor=0.7).disposition == "chargeable"
    assert decide(answer={**NEW, "confidence": 0.69}, floor=0.7).disposition == "evidence_only"


def test_confirmed_baseline_mark_is_excluded_even_if_the_model_says_new():
    mark = {"angle": 2, "part": "side_panel", "damage_class": "dent", "bbox": [0.38, 0.38, 0.12, 0.12], "confirmed": True}
    assert decide(part="side_panel", cls="dent", marks=[mark]).disposition == "excluded_baseline"  # I3
    unconfirmed = {**mark, "confirmed": False}
    assert decide(part="side_panel", cls="dent", marks=[unconfirmed]).disposition == "chargeable"
    other_angle = {**mark, "angle": 5}
    assert decide(part="side_panel", cls="dent", marks=[other_angle]).disposition == "chargeable"


def test_tap_inside_a_low_comparability_region_cannot_be_charged():
    low = [[0.25, 0.25, 0.25, 0.25], [0.50, 0.25, 0.25, 0.25]]
    assert decide(low=low).disposition == "not_comparable"
    assert decide(low=[[0.0, 0.0, 0.1, 0.1]]).disposition == "chargeable"


# --- settlement --------------------------------------------------------------------------------
def line(i, part, cls, decision, disposition="chargeable"):
    return {"id": f"L{i}", "part": part, "damage_class": cls, "disposition": disposition,
            "price_cents": T.price(part, cls) if disposition == "chargeable" else None, "renter_decision": decision}


def plan(lines, deposit=10000, fee=1500, force=False):
    return settle_plan(fee_cents=fee, deposit_cents=deposit, authorized_cents=fee + deposit, fee_captured_cents=fee,
                       lines=lines, tariff_price=T.price, force=force)


def test_clean_return_voids():
    p = plan([line(1, "side_panel", "dent", None, "excluded_baseline")])
    assert p.void and p.capture_cents == 0 and not p.invoice_items


def test_accepted_line_is_one_final_capture_of_exactly_its_tariff_price():
    p = plan([line(1, "mirror_housing", "crack", "accepted"), line(2, "side_panel", "dent", None, "excluded_baseline"),
              line(3, "rear_panel", "scuff", None, "not_comparable")])
    assert not p.void and p.capture_cents == 1800 and not p.invoice_items


def test_contested_line_leaves_the_hold_as_an_invoice_at_its_tariff_price():
    p = plan([line(1, "mirror_housing", "crack", "accepted"), line(2, "front_fairing", "dent", "contested")])
    assert p.capture_cents == 1800
    assert [(i["kind"], i["amount_cents"]) for i in p.invoice_items] == [("contested", 4500)]


def test_all_contested_voids_the_hold_and_invoices():
    p = plan([line(1, "front_fairing", "dent", "contested")])
    assert p.void and p.invoice_cents == 4500


def test_accepted_above_the_deposit_captures_the_deposit_and_invoices_the_overage():
    p = plan([line(1, "front_fairing", "crack", "accepted"), line(2, "front_fairing", "dent", "accepted")], deposit=10000)
    assert p.capture_cents == 10000
    assert [(i["kind"], i["amount_cents"]) for i in p.invoice_items] == [("overage", 1000)]


def test_undecided_lines_block_settle_unless_the_expiry_guard_forces_it():
    lines = [line(1, "mirror_housing", "crack", None)]
    with pytest.raises(SettleBlocked):
        plan(lines)
    p = plan(lines, force=True)  # I5: default outcome is release; nothing unanswered is invoiced
    assert p.void and p.invoice_cents == 0


def test_a_tampered_line_price_blocks_settle():
    l = line(1, "mirror_housing", "crack", "accepted")
    l["price_cents"] = 9000
    with pytest.raises(SettleBlocked):
        plan([l])  # I1


def test_non_chargeable_lines_are_never_paid_even_if_marked_accepted():
    p = plan([line(1, "side_panel", "dent", "accepted", "excluded_baseline"),
              line(2, "rear_panel", "scuff", "accepted", "evidence_only")])
    assert p.void and p.capture_cents == 0 and not p.invoice_items  # I3


def test_captures_never_exceed_the_authorization():
    with pytest.raises(SettleBlocked):
        settle_plan(fee_cents=1500, deposit_cents=10000, authorized_cents=10000, fee_captured_cents=1500,
                    lines=[line(1, "front_fairing", "crack", "accepted"), line(2, "front_fairing", "dent", "accepted")],
                    tariff_price=T.price)  # I2


# --- state machine -----------------------------------------------------------------------------
def test_happy_path_transitions():
    path = ["DRAFT", "APPROVED", "HELD", "OUT", "RETURNED", "CLAIMED", "PROPOSED", "SETTLED", "INVOICED", "CLOSED"]
    for a, b in zip(path, path[1:], strict=False):
        check_transition(a, b)


@pytest.mark.parametrize("a,b", [("DRAFT", "SETTLED"), ("OUT", "SETTLED"), ("SETTLED", "SETTLED"),
                                 ("RELEASED", "SETTLED"), ("CLOSED", "OUT"), ("HELD", "PROPOSED")])
def test_illegal_transitions(a, b):
    with pytest.raises(IllegalTransition):
        check_transition(a, b)


# --- reauth / expiry / fines --------------------------------------------------------------------
def test_reauth_once_from_day_four():
    assert not rules.needs_reauth("OUT", 2.9, False)
    assert rules.needs_reauth("OUT", 3.0, False)
    assert not rules.needs_reauth("OUT", 5, True)
    assert not rules.needs_reauth("SETTLED", 5, False)


def test_expiry_guard_releases_before_the_hold_expires():
    assert rules.expiry_guard_due("PROPOSED", 27.5)
    assert not rules.expiry_guard_due("PROPOSED", 10)
    assert not rules.expiry_guard_due("OUT", 28)


def fine(**kw):
    args = dict(plate_read="B 0000 JMN", rental_plate="B0000JMN", ticket_time="2026-10-15T10:00:00+07:00",
                pickup_at="2026-10-15T08:00:00+07:00", return_at="2026-10-15T18:00:00+07:00",
                violation_read="pasal_291_1", ceilings=T.fine_ceilings, ticket_amount_idr=250000,
                idr_per_usd=T.idr_per_usd, admin_fee_cents=T.admin_fee_cents)
    args.update(kw)
    return rules.fine_quote(**args)


def test_fine_matches_plate_and_window_and_is_capped_by_the_article_ceiling():
    q = fine()
    assert q.chargeable and q.amount_cents == round(250000 / T.idr_per_usd * 100) + T.admin_fee_cents
    capped = fine(ticket_amount_idr=900000)
    assert capped.capped and capped.amount_cents == q.amount_cents


@pytest.mark.parametrize("kw", [{"plate_read": "B 9999 ZZ"}, {"ticket_time": "2026-10-16T10:00:00+07:00"},
                                {"violation_read": "pasal_999"}, {"plate_read": None}])
def test_fine_not_chargeable(kw):
    assert not fine(**kw).chargeable


def test_tariff_hash_is_stable_and_public_view_has_no_admin_line():
    assert T.sha256 == tariff.load("tv1").sha256 and len(T.sha256) == 64
    assert all(l["damage_class"] in tariff.DAMAGE_CLASSES for l in T.public()["lines"])


def test_fine_window_compares_real_instants_across_offsets():
    # 16:00 WIB on the 15th = 09:00 UTC, before a pickup at 10:00 UTC → outside, although "16:00" > "10:00" as text
    q = fine(ticket_time="2026-10-15T16:00:00+07:00", pickup_at="2026-10-15T10:00:00+00:00",
             return_at="2026-10-15T20:00:00+00:00")
    assert not q.chargeable and "outside" in q.reason
    q = fine(ticket_time="2026-10-15T18:00:00+07:00", pickup_at="2026-10-15T10:00:00+00:00",
             return_at="2026-10-15T20:00:00+00:00")
    assert q.chargeable


def test_fine_time_without_an_offset_is_refused():
    assert not fine(ticket_time="2026-10-15 10:00").chargeable

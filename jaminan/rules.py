"""The money rules, as pure functions. Nothing here talks to PayPal or the model; everything that
decides an amount lives here so it can be tested exhaustively.

Invariants (asserted by tests/test_rules.py):
  I1  No capture amount is ever produced by the model: every amount is the fee, a sum of tariff prices of
      renter-accepted lines, or a ceiling-capped fine plus the published admin fee.
  I2  Σ captures on one authorization ≤ the authorized amount H = fee + deposit.
  I3  A line matching a confirmed baseline mark (angle, part, class) can never be accepted or charged.
  I4  Every PayPal write has a deterministic request id (jaminan.paypal.request_id).
  I5  Default outcome is release: a return nobody acts on is voided before the hold expires.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# ---------------------------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------------------------
TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"APPROVED"},
    "APPROVED": {"HELD", "RELEASED"},          # authorization exists, fee not captured yet
    "HELD": {"OUT", "RELEASED"},               # fee captured (final_capture=false)
    "OUT": {"RETURNED", "RELEASED"},           # baseline confirmed, tracking written; reauthorize keeps OUT
    "RETURNED": {"CLAIMED", "PROPOSED", "RELEASED"},
    "CLAIMED": {"CLAIMED", "PROPOSED", "RELEASED"},
    "PROPOSED": {"SETTLED", "RELEASED"},
    "SETTLED": {"INVOICED", "CLOSED"},
    "RELEASED": {"INVOICED", "CLOSED"},
    "INVOICED": {"CLOSED"},
    "CLOSED": set(),
}
OPEN_HOLD_STATES = {"APPROVED", "HELD", "OUT", "RETURNED", "CLAIMED", "PROPOSED"}


class IllegalTransition(ValueError):
    pass


def check_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, set()):
        raise IllegalTransition(f"{current} → {target} is not a rental transition")


# ---------------------------------------------------------------------------------------------
# Pointed claims → disposition (the ONE pricing path)
# ---------------------------------------------------------------------------------------------
DISPOSITIONS = ("chargeable", "excluded_baseline", "not_comparable", "no_mark", "class_mismatch", "retake",
                "comparison_unavailable", "evidence_only")

ANSWER_TEXT = {
    "chargeable": "new — priced from tariff",
    "excluded_baseline": "visible at pickup — cannot be charged",
    "not_comparable": "the shared baseline can't show this — cannot be charged",
    "no_mark": "no mark found at return — cannot be charged",
    "class_mismatch": "doesn't look like a {cls} — can't be paid from the hold",
    "retake": "not the same view — retake",
    "comparison_unavailable": "comparison unavailable — nothing charged from the hold",
    "evidence_only": "kept in the evidence pack — not priced",
}
ANSWER_TEXT_ID = {
    "chargeable": "baru — harga dari tarif",
    "excluded_baseline": "terlihat saat ambil — tidak bisa ditagih",
    "not_comparable": "foto awal tidak bisa menunjukkan ini — tidak bisa ditagih",
    "no_mark": "tidak ada tanda saat kembali — tidak bisa ditagih",
    "class_mismatch": "tidak terlihat seperti {cls} — tidak bisa dibayar dari jaminan",
    "retake": "bukan sudut yang sama — foto ulang",
    "comparison_unavailable": "perbandingan tidak tersedia — tidak ada yang ditagih",
    "evidence_only": "disimpan di paket bukti — tanpa harga",
}

CLAIM_FIELDS = ("mark_at_return", "class_consistent", "visible_at_pickup", "pickup_comparable", "same_view")


@dataclass
class Decision:
    disposition: str
    price_cents: int | None
    reason: str

    def text(self, cls: str = "", lang: str = "en") -> str:
        t = (ANSWER_TEXT_ID if lang == "id" else ANSWER_TEXT)[self.disposition]
        return t.format(cls=cls.replace("_", " "))


def bbox_overlap(a: Iterable[float], b: Iterable[float]) -> float:
    """Fraction of box a covered by box b; boxes are normalized [x, y, w, h]."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    return (ix * iy) / (aw * ah) if aw * ah > 0 else 0.0


def low_comparability_share(bbox: Iterable[float], low_tiles: list[list[float]]) -> float:
    """Share of a tap box that falls in the pickup frame's low-comparability tiles (from the frame gate)."""
    return min(1.0, sum(bbox_overlap(bbox, t) for t in low_tiles))


def decide_claim(*, answer: dict[str, Any] | None, serving_model: str | None, benchmarked_model: str,
                 part: str, damage_class: str, angle: int, tap_bbox: list[float], price_cents: int | None,
                 baseline_marks: list[dict[str, Any]], pickup_low_tiles: list[list[float]],
                 chargeable_classes: Iterable[str], confidence_floor: float) -> Decision:
    """Code decides — in this order. The model only ever answers the yes/no questions in `answer`."""
    # I3: a confirmed baseline mark of the same angle + part + class is excluded whatever the model says
    for m in baseline_marks:
        if m.get("confirmed") and m.get("angle") == angle and m.get("part") == part and \
                m.get("damage_class") == damage_class and \
                (not m.get("bbox") or bbox_overlap(tap_bbox, m["bbox"]) > 0 or bbox_overlap(m["bbox"], tap_bbox) > 0):
            return Decision("excluded_baseline", None, "matches a mark confirmed in the shared baseline (I3)")
    # refusal, timeout, schema failure, or any model other than the benchmarked one
    if answer is None:
        return Decision("comparison_unavailable", None, "no valid model answer (refusal, timeout or schema failure)")
    if not benchmarked_model or serving_model != benchmarked_model:
        return Decision("comparison_unavailable", None,
                        f"served by {serving_model or 'unknown'}, not the benchmarked model "
                        f"({benchmarked_model or 'none pinned yet'})")
    if any(not isinstance(answer.get(f), bool) for f in CLAIM_FIELDS):
        return Decision("comparison_unavailable", None, "model answer failed the schema")
    if not answer["same_view"]:
        return Decision("retake", None, "pickup and return frames are not the same view")
    if not answer["mark_at_return"]:
        return Decision("no_mark", None, "no mark at the tapped spot on the return frame")
    if answer["visible_at_pickup"]:
        return Decision("excluded_baseline", None, "the mark is visible in the pickup frame")
    if not answer["pickup_comparable"]:
        return Decision("not_comparable", None, "the pickup frame cannot show this spot (focus, glare, occlusion)")
    if low_comparability_share(tap_bbox, pickup_low_tiles) >= 0.5:
        return Decision("not_comparable", None, "the spot lies in a low-comparability region flagged at baseline confirm")
    if not answer["class_consistent"]:
        return Decision("class_mismatch", None, f"the mark does not look like a {damage_class}")
    conf = answer.get("confidence")
    if not isinstance(conf, (int, float)) or conf < confidence_floor:
        return Decision("evidence_only", None, f"confidence {conf} below the floor {confidence_floor}")
    if damage_class not in set(chargeable_classes):
        return Decision("evidence_only", None, f"class {damage_class} is not enabled by the bench yet")
    if price_cents is None:
        return Decision("evidence_only", None, f"no published tariff line for {part}/{damage_class}")
    return Decision("chargeable", price_cents, "new since pickup; priced from the published tariff")


# ---------------------------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------------------------
@dataclass
class SettlePlan:
    capture_cents: int                      # one capture, final_capture=true (0 → void)
    void: bool
    accepted: list[dict] = field(default_factory=list)
    contested: list[dict] = field(default_factory=list)
    invoice_items: list[dict] = field(default_factory=list)   # overage + contested priced lines
    evidence_only: list[dict] = field(default_factory=list)

    @property
    def invoice_cents(self) -> int:
        return sum(i["amount_cents"] for i in self.invoice_items)


class SettleBlocked(ValueError):
    pass


def settle_plan(*, fee_cents: int, deposit_cents: int, authorized_cents: int, fee_captured_cents: int,
                lines: list[dict], tariff_price, force: bool = False) -> SettlePlan:
    """The hold only pays lines the renter accepted.

    `lines` are findings; only `chargeable` ones can be accepted. `tariff_price(part, cls)` re-prices each
    accepted line from the published tariff (I1: the stored price is never trusted). `force` (expiry guard,
    I5) releases instead of blocking: undecided lines are never paid from the hold and never invoiced —
    the renter did not contest them, so they stay in the evidence pack.
    """
    chargeable = [l for l in lines if l.get("disposition") == "chargeable"]
    undecided = [l for l in chargeable if l.get("renter_decision") not in ("accepted", "contested")]
    if undecided and not force:
        raise SettleBlocked(f"{len(undecided)} chargeable line(s) still need the renter's accept or contest")
    accepted, contested = [], []
    for l in chargeable:
        if l.get("renter_decision") not in ("accepted", "contested"):
            continue  # only reachable with force=True
        price = tariff_price(l["part"], l["damage_class"])
        if price is None or price != l.get("price_cents"):
            raise SettleBlocked(f"line {l.get('id')} price does not match the published tariff (I1)")
        (accepted if l.get("renter_decision") == "accepted" else contested).append({**l, "price_cents": price})
    for l in accepted:  # I3 is enforced at decide time; re-assert here
        if l.get("disposition") != "chargeable":
            raise SettleBlocked("only chargeable lines can be paid from the hold (I3)")
    total_accepted = sum(l["price_cents"] for l in accepted)
    capture = min(total_accepted, deposit_cents)
    if fee_captured_cents + capture > authorized_cents:   # I2 (PayPal enforces too; we check first)
        raise SettleBlocked("captures would exceed the authorized amount (I2)")
    items: list[dict] = []
    overage = max(total_accepted - deposit_cents, 0)
    if overage:
        items.append({"name": "Accepted damage above the deposit hold", "amount_cents": overage, "kind": "overage"})
    for l in contested:
        items.append({"name": f"Contested: {l['part'].replace('_', ' ')} — {l['damage_class'].replace('_', ' ')}",
                      "amount_cents": l["price_cents"], "kind": "contested", "line_id": l.get("id")})
    evidence = [l for l in lines if l.get("disposition") != "chargeable"]
    return SettlePlan(capture_cents=capture, void=capture == 0, accepted=accepted, contested=contested,
                      invoice_items=items, evidence_only=evidence)


# ---------------------------------------------------------------------------------------------
# Long rentals, expiry, fines
# ---------------------------------------------------------------------------------------------
HONOR_DAYS = 3          # PayPal honor period; reauthorize allowed once, Day 4–29
AUTH_VALID_DAYS = 29


def needs_reauth(state: str, age_days: float, reauthorized: bool) -> bool:
    return state in {"HELD", "OUT"} and age_days >= HONOR_DAYS and age_days < AUTH_VALID_DAYS and not reauthorized


def expiry_guard_due(state: str, age_days: float, margin_days: float = 2.0) -> bool:
    """I5: a returned-but-unsettled rental is released before its hold expires."""
    return state in {"RETURNED", "CLAIMED", "PROPOSED"} and age_days >= AUTH_VALID_DAYS - margin_days


def _aware(ts: str | None):
    """Parse an ISO 8601 timestamp; a value without an offset is refused (WIB vs UTC would shift it 7 h)."""
    from datetime import datetime
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None


@dataclass
class FineQuote:
    chargeable: bool
    reason: str
    amount_cents: int = 0
    ceiling_idr: int = 0
    capped: bool = False


def fine_quote(*, plate_read: str | None, rental_plate: str, ticket_time: str | None, pickup_at: str,
               return_at: str | None, violation_read: str | None, ceilings: dict[str, tuple[str, int]],
               ticket_amount_idr: int, idr_per_usd: float, admin_fee_cents: int) -> FineQuote:
    """Fine is chargeable iff plate matches AND ticket time is inside the rental window; amount =
    min(ticket amount, ceiling of the article the model read) / pinned rate + published admin fee."""
    norm = lambda p: "".join(ch for ch in (p or "").upper() if ch.isalnum())  # noqa: E731
    if not plate_read or norm(plate_read) != norm(rental_plate):
        return FineQuote(False, "plate on the ticket does not match the rental's vehicle")
    t, start, end = _aware(ticket_time), _aware(pickup_at), _aware(return_at) if return_at else None
    if t is None or start is None:
        return FineQuote(False, "ticket time could not be read as a date and time with its offset")
    if not (start <= t <= (end or t)):
        return FineQuote(False, "ticket time is outside the rental window")
    if violation_read not in ceilings:
        return FineQuote(False, "violation article not in the published closed list")
    ceiling = ceilings[violation_read][1]
    idr = min(int(ticket_amount_idr), ceiling)
    usd_cents = int(round(idr / idr_per_usd * 100))
    return FineQuote(True, "plate and time match the rental", usd_cents + admin_fee_cents, ceiling,
                     capped=int(ticket_amount_idr) > ceiling)

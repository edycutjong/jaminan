// The AI-generated test pair (evidence/generated-pair/): turns the recorded run into what /app/judge shows.
// Not a benchmark: one angle, two pointed claims, AI-generated images (not photographs).

export const GENERATED_LABEL = "AI-generated test images (not photographs)";

type Run = {
  repeat: number; at: string; model: string | null; request_id: string | null; error: string | null;
  answer: { confidence: number; rationale: string } | null;
  disposition: string; answer_text: string; model_reading: string; reading_disposition: string; matches_expected: boolean;
};
type Claim = {
  id: string; expected: string; part: string; damage_class: string; bbox: number[]; tariff_price_cents: number | null;
  runs: Run[];
};
export type GeneratedRun = { recorded_at: string; requested_model: string; benchmarked_model: string | null; claims: Claim[] };

const TRUTH: Record<string, string> = {
  old: "old: the same scuff is in the pickup image",
  new: "new: both mirrors are missing at return",
};
// Why the shop's claim reads as it does (from each claim's note in the recorded run).
const WHY: Record<string, string> = {
  old: "The tariff has no scuff line on the fairing, so the shop names a dent: an over-claim on an old mark.",
  new: "A missing part, asked about as a \u201cmark\u201d at the tap: the claim question fits it badly.",
};
const READ: Record<string, string> = {
  old: "visible at pickup (old)",
  new: "new since pickup",
  "new, other class": "a mark at return, but not this part and class",
  "no mark": "no mark at the tap",
  "no answer": "no valid answer",
};

export function label(s: string) {
  return s.replace(/_/g, " ");
}

export function tally(right: number, n: number) {
  if (right === 0) return `wrong in all ${n} calls`;
  return right === n ? `right in all ${n} calls` : `right in ${right} of ${n} calls`;
}

export function summarize(run: GeneratedRun) {
  return run.claims.map((c) => {
    const readings = Array.from(new Set(c.runs.map((r) => r.model_reading)));
    const right = c.runs.filter((r) => r.matches_expected).length;
    const pricedIfPinned = c.runs.some((r) => r.reading_disposition === "chargeable");
    return {
      id: c.id,
      claim: `${label(c.part)} — ${label(c.damage_class)}`,
      bbox: c.bbox,
      truth: TRUTH[c.expected] ?? c.expected,
      why: WHY[c.expected] ?? "",
      read: readings.map((x) => READ[x] ?? x).join(" / "),
      tally: tally(right, c.runs.length),
      wrong: right < c.runs.length,
      rationale: c.runs[0]?.answer?.rationale ?? "",
      appAnswer: Array.from(new Set(c.runs.map((r) => r.answer_text))).join(" / "),
      models: Array.from(new Set(c.runs.map((r) => r.model ?? "unknown"))).join(", "),
      requestIds: c.runs.map((r) => r.request_id ?? "—"),
      pricedIfPinnedCents: pricedIfPinned ? c.tariff_price_cents : null,
    };
  });
}

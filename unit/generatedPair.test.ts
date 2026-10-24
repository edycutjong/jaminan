import { describe, expect, it } from "vitest";
import { GENERATED_LABEL, GeneratedRun, label, summarize, tally } from "@/lib/generatedPair";
import recorded from "@/evidence/generated-pair/run-2026-10-25.json";

const run = (over: Partial<GeneratedRun["claims"][number]["runs"][number]> = {}, expected = "old"): GeneratedRun => ({
  recorded_at: "t", requested_model: "m", benchmarked_model: null,
  claims: [{
    id: "C9", expected, part: "side_panel", damage_class: "scuff", bbox: [0, 0, 1, 1], tariff_price_cents: 1500,
    runs: [{ repeat: 1, at: "t", model: "m", request_id: "r1", error: null, answer: { confidence: 0.9, rationale: "why" },
      disposition: "comparison_unavailable", answer_text: "comparison unavailable — nothing charged from the hold",
      model_reading: "old", reading_disposition: "excluded_baseline", matches_expected: true, ...over }],
  }],
});

describe("generated pair summary", () => {
  it("carries the disclosure label verbatim", () => {
    expect(GENERATED_LABEL).toBe("AI-generated test images (not photographs)");
  });
  it("reports the recorded run as it happened: both claims read wrong, nothing charged", () => {
    const [c1, c2] = summarize(recorded as GeneratedRun);
    expect(c1.claim).toBe("front fairing — dent");
    expect(c1.read).toBe("new since pickup");
    expect(c1.tally).toBe("wrong in all 3 calls");
    expect(c1.wrong).toBe(true);
    expect(c1.pricedIfPinnedCents).toBe(4500);
    expect(c1.appAnswer).toBe("comparison unavailable — nothing charged from the hold");
    expect(c1.models).toBe("qwen3-vl-plus");
    expect(c1.requestIds).toHaveLength(3);
    expect(c2.read).toBe("a mark at return, but not this part and class");
    expect(c2.truth).toBe("new: both mirrors are missing at return");
    expect(c2.pricedIfPinnedCents).toBeNull();
  });
  it("counts a right reading and falls back on unknown values", () => {
    const [c] = summarize(run());
    expect([c.tally, c.wrong, c.read, c.rationale, c.pricedIfPinnedCents]).toEqual(["right in all 1 calls", false, "visible at pickup (old)", "why", null]);
    const [u] = summarize(run({ model_reading: "odd", model: null, request_id: null, answer: null }, "weird"));
    expect([u.read, u.truth, u.models, u.requestIds[0], u.rationale]).toEqual(["odd", "weird", "unknown", "—", ""]);
    const [none] = summarize({ ...run(), claims: [{ ...run().claims[0], runs: [] }] });
    expect([none.tally, none.wrong, none.rationale]).toEqual(["wrong in all 0 calls", false, ""]);
  });
  it("words the tally without a rate", () => {
    expect(tally(2, 3)).toBe("right in 2 of 3 calls");
  });
  it("labels a part with spaces", () => {
    expect(label("missing_part")).toBe("missing part");
  });
});

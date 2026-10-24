import { describe, expect, it } from "vitest";
import { answerText } from "@/lib/answers";
import type { Finding } from "@/lib/api";

const f = (disposition: string) => ({ disposition }) as Finding;

describe("answerText", () => {
  it("states why a line is or is not chargeable, in English by default", () => {
    expect(answerText(f("chargeable"))).toBe("new — priced from tariff");
    expect(answerText(f("excluded_baseline"), "en")).toBe("visible at pickup — cannot be charged");
  });
  it("answers in Bahasa Indonesia on request", () => {
    expect(answerText(f("no_mark"), "id")).toBe("tidak ada tanda saat kembali — tidak bisa ditagih");
  });
  it("falls back to the raw disposition for one it does not know", () => {
    expect(answerText(f("something_new"))).toBe("something_new");
    expect(answerText(f("something_new"), "id")).toBe("something_new");
  });
});

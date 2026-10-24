import type { Finding } from "./api";

const EN: Record<string, string> = {
  chargeable: "new — priced from tariff",
  excluded_baseline: "visible at pickup — cannot be charged",
  not_comparable: "the shared baseline can't show this — cannot be charged",
  no_mark: "no mark found at return — cannot be charged",
  class_mismatch: "doesn't look like that — can't be paid from the hold",
  retake: "not the same view — retake",
  comparison_unavailable: "comparison unavailable — nothing charged from the hold",
  evidence_only: "kept in the evidence pack — not priced",
};
const ID: Record<string, string> = {
  chargeable: "baru — harga dari tarif",
  excluded_baseline: "terlihat saat ambil — tidak bisa ditagih",
  not_comparable: "foto awal tidak bisa menunjukkan ini — tidak bisa ditagih",
  no_mark: "tidak ada tanda saat kembali — tidak bisa ditagih",
  class_mismatch: "tidak sesuai jenisnya — tidak bisa dibayar dari jaminan",
  retake: "bukan sudut yang sama — foto ulang",
  comparison_unavailable: "perbandingan tidak tersedia — tidak ada yang ditagih",
  evidence_only: "disimpan di paket bukti — tanpa harga",
};

export function answerText(f: Finding, lang: "en" | "id" = "en") {
  return (lang === "id" ? ID : EN)[f.disposition] || f.disposition;
}

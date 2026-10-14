"use client";
import { useEffect, useRef, useState } from "react";
import CropPair from "@/components/CropPair";
import { answerText } from "@/components/Stub";
import TapLayer from "@/components/TapLayer";
import { ANGLE_NAMES, ApiError, CLASS_ID, Finding, PART_ID, Rental, Suggestion, TariffLine, api, human, usd } from "@/lib/api";

/** "You're the shop — tap what you'd charge." The owner points; the shared baseline answers. */
export default function ShopReturn({ r, skey, onChange, english = false }: {
  r: Rental; skey: string; onChange: (r: Rental) => void; english?: boolean;
}) {
  const t = (id: string, en: string) => (english ? en : id);
  const [angle, setAngle] = useState(r.findings[0]?.angle || r.suggestions.find((s) => s.status === "shown")?.angle || 1);
  const [pending, setPending] = useState<number[] | null>(null);
  const [sugg, setSugg] = useState<Suggestion | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [last, setLast] = useState<Finding | null>(null);
  const ran = useRef(false);

  const run = async (label: string, fn: () => Promise<any>) => {
    setBusy(label); setErr(null);
    try { return await fn(); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); return null; } finally { setBusy(null); }
  };
  useEffect(() => {
    if (ran.current || (r as any).suggest_run || !["RETURNED", "CLAIMED"].includes(r.state)) return;
    ran.current = true;
    run("suggest", () => api(`/rentals/${r.id}/return/suggest`, { method: "POST", key: skey })).then((x) => x && onChange(x));
  }, [r, skey]); // eslint-disable-line react-hooks/exhaustive-deps

  const claim = async (line: TariffLine, bbox: number[], suggestion_id?: string) => {
    const out = await run("claim", () => api(`/rentals/${r.id}/claims`, {
      key: skey, body: { angle, bbox, part: line.part, damage_class: line.damage_class, suggestion_id },
    }));
    if (out) { onChange(out.rental); setLast(out.finding); setPending(null); setSugg(null); }
  };
  const lines = r.tariff.lines;
  const priced = r.findings.filter((f) => f.disposition === "chargeable");
  const open = ["RETURNED", "CLAIMED"].includes(r.state);
  const suggLine = sugg ? lines.find((l) => l.part === sugg.part && l.damage_class === sugg.damage_class) : null;

  return (
    <div>
      <h1>{t("Cek pengembalian", "Return check")}</h1>
      <p className="muted" style={{ marginTop: 0 }}>{t("Ketuk tanda yang ingin ditagih, pilih dari daftar tarif. Foto awal yang disepakati bersama yang menjawab.", "Tap the mark you want to charge and pick it from the tariff list. The shared pickup photos answer.")}
        {!english ? <><br /><span className="caption-en">Tap the mark you want to charge and pick it from the tariff list. The shared pickup photos answer.</span></> : null}</p>
      {!r.benchmarked_model ? (
        <div className="note small">{t("Bench model belum dipasang: tidak ada baris yang bisa ditagih dari jaminan sampai uji akurasi selesai.", "No vision model is pinned by the accuracy bench yet, so no line can be charged from the hold.")}
          {!english ? <><br /><span className="caption-en">No vision model is pinned by the accuracy bench yet, so no line can be charged from the hold.</span></> : null}</div>
      ) : null}
      <div className="angles" style={{ margin: "12px 0" }}>
        {[1, 2, 3, 4, 5, 6, 7, 8].map((a) => {
          const n = r.findings.filter((f) => f.angle === a).length + r.suggestions.filter((s) => s.angle === a && s.status === "shown").length;
          return (
            <button key={a} className={`angle ${a === angle ? "current" : ""} done`} onClick={() => { setAngle(a); setPending(null); setSugg(null); }}
              aria-label={`angle ${a}`}>
              <span>{a} {english ? ANGLE_NAMES[a].en : ANGLE_NAMES[a].id}{n ? ` · ${n}` : ""}</span>
            </button>
          );
        })}
      </div>
      {busy === "suggest" ? <p className="small muted"><span className="spin" /> {t("model mencari kerusakan baru (saran)…", "the model is looking for new damage (suggested taps)…")}</p> : null}
      <TapLayer r={r} angle={angle} pending={pending} onTap={(b) => { if (open) { setPending(b); setSugg(null); } }} onSuggestion={(s) => { setSugg(s); setPending(null); }} />
      <p className="small muted" style={{ margin: "6px 0 0" }}>{t("Garis putus-putus biru = saran model. Arsir = area foto awal yang silau/buram.", "Dashed blue = the model's suggested tap. Hatched = glare/blur at pickup.")}</p>

      {sugg && open ? (
        <div className="paper" style={{ marginTop: 12 }}>
          <div className="label">{t("Saran model", "Suggested tap")}</div>
          <p style={{ margin: "4px 0 10px" }}><strong>{english ? `${human(sugg.part)} — ${human(sugg.damage_class)}` : `${PART_ID[sugg.part] || human(sugg.part)} — ${CLASS_ID[sugg.damage_class] || sugg.damage_class}`}</strong>
            <br /><span className="small muted">{t("Saran tidak menagih apa pun sampai toko mengonfirmasi.", "A suggestion charges nothing until the shop confirms it.")}</span></p>
          <div className="row">
            <button className="btn" disabled={!!busy || !suggLine} onClick={() => suggLine && claim(suggLine, sugg.bbox_return, sugg.id)}>
              {busy === "claim" ? <span className="spin" /> : suggLine ? `${t("Konfirmasi", "Confirm")} · ${usd(suggLine.price_cents)}` : t("Tidak ada di tarif", "Not in the tariff")}
            </button>
            <button className="btn ghost" disabled={!!busy} onClick={async () => { const x = await run("dismiss", () => api(`/rentals/${r.id}/suggestions/${sugg.id}/dismiss`, { method: "POST", key: skey })); if (x) { onChange(x); setSugg(null); } }}>
              {t("Abaikan", "Dismiss")}
            </button>
          </div>
        </div>
      ) : null}

      {pending && open ? (
        <div className="paper" style={{ marginTop: 12 }}>
          <div className="label">{t("Pilih dari daftar tarif", "Pick from the published tariff")}</div>
          <div className="picker" style={{ marginTop: 6 }}>
            {lines.map((l) => (
              <button key={`${l.part}/${l.damage_class}`} disabled={!!busy} onClick={() => claim(l, pending)}>
                <span>{english ? `${human(l.part)} — ${human(l.damage_class)}` : `${PART_ID[l.part] || human(l.part)} — ${CLASS_ID[l.damage_class]}`}
                  {!english ? <span className="caption-en"> · {human(l.part)} {human(l.damage_class)}</span> : null}</span>
                <span className="data">{usd(l.price_cents)}</span>
              </button>
            ))}
          </div>
          {busy === "claim" ? <p className="small muted"><span className="spin" /> {t("membandingkan dengan foto awal…", "comparing with the pickup photos…")}</p> : null}
        </div>
      ) : null}

      {last ? (
        <div className={`paper ${last.disposition === "chargeable" ? "" : "line excluded"}`} style={{ marginTop: 12, display: "block" }} role="status">
          <strong>{human(last.part)} — {human(last.damage_class)}</strong>
          <CropPair f={last} lang={english ? "en" : "id"} />
          <p style={{ margin: "4px 0 0" }}><strong>{answerText(last, english ? "en" : "id")}</strong>
            {!english ? <><br /><span className="caption-en">{answerText(last, "en")}</span></> : null}</p>
          <p className="small muted" style={{ margin: "4px 0 0" }}>{last.reason}{last.model ? ` · model ${last.model}` : ""}</p>
        </div>
      ) : null}

      {err ? <div className="toast" role="alert" style={{ marginTop: 10 }}>{err}</div> : null}

      <h2>{t("Baris", "Lines")} ({r.findings.length})</h2>
      {r.findings.length === 0 ? <p className="muted small">{t("Belum ada tanda yang diketuk.", "No marks tapped yet.")}</p> : null}
      {r.findings.map((f) => (
        <div key={f.id} className={`line ${f.disposition === "chargeable" ? "" : "excluded"}`}>
          <span className="what">{human(f.part)} — {human(f.damage_class)} <span className="small muted">· {t("sudut", "angle")} {f.angle}</span></span>
          <span className="price">{f.disposition === "chargeable" ? usd(f.price_cents) : "—"}</span>
          <span className="why">{answerText(f, english ? "en" : "id")}</span>
        </div>
      ))}
      {open ? (
        <div className="stack" style={{ marginTop: 16 }}>
          {priced.length ? (
            <button className="btn" disabled={!!busy} onClick={async () => { const x = await run("propose", () => api(`/rentals/${r.id}/propose`, { method: "POST", key: skey })); if (x) onChange(x); }}>
              {t(`Kirim ${priced.length} baris ke penyewa`, `Send ${priced.length} line${priced.length === 1 ? "" : "s"} to the renter`)}
            </button>
          ) : (
            <button className="btn release" disabled={!!busy} onClick={async () => { const x = await run("release", () => api(`/rentals/${r.id}/release`, { method: "POST", key: skey })); if (x) onChange(x); }}>
              {busy === "release" ? <span className="spin" /> : t("Lepas jaminan · tidak ada kerusakan baru", "Release the hold · no new damage")}
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}

"use client";
import { useState } from "react";
import CropPair from "@/components/CropPair";
import Stub, { answerText } from "@/components/Stub";
import { ApiError, Rental, api, human, usd } from "@/lib/api";

/** The devastating moment, on the renter's own phone: accept or contest each priced line, then settle. */
export default function RenterSettle({ r, rkey, onChange }: { r: Rental; rkey: string; onChange: (r: Rental) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const priced = r.findings.filter((f) => f.disposition === "chargeable");
  const refused = r.findings.filter((f) => f.disposition !== "chargeable");
  const undecided = priced.filter((f) => !f.renter_decision).length;
  const act = async (label: string, fn: () => Promise<Rental>) => {
    setBusy(label); setErr(null);
    try { onChange(await fn()); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(null); }
  };
  if (r.settlement) return <Stub r={r} />;
  return (
    <div>
      <h1>Settle your deposit</h1>
      <p className="muted">The shop pointed at {r.findings.length} mark{r.findings.length === 1 ? "" : "s"}. Here is what the pickup photos you both confirmed say about each one.</p>
      <div className="note small">The hold only pays lines you accept — a contested line arrives as an itemized PayPal invoice at its tariff price.</div>
      {priced.map((f) => (
        <div key={f.id} className="paper" style={{ marginTop: 14 }}>
          <div className="row" style={{ alignItems: "baseline" }}>
            <strong>{human(f.part)} — {human(f.damage_class)}</strong>
            <span className="amount" style={{ textAlign: "right", flex: "0 0 auto", fontSize: 22 }}>{usd(f.price_cents)}</span>
          </div>
          <CropPair f={f} />
          <p className="small" style={{ margin: "4px 0 10px" }}>{answerText(f)} · tariff {r.tariff_version_id}</p>
          <div className="row">
            <button className={`btn ${f.renter_decision === "accepted" ? "accept" : "ghost"}`} disabled={!!busy}
              onClick={() => act(f.id + "a", () => api(`/rentals/${r.id}/lines/${f.id}/decision`, { body: { decision: "accepted" }, key: rkey }))}>
              {f.renter_decision === "accepted" ? "Accepted" : "Accept"}
            </button>
            <button className={`btn ${f.renter_decision === "contested" ? "" : "ghost"}`} disabled={!!busy}
              onClick={() => act(f.id + "c", () => api(`/rentals/${r.id}/lines/${f.id}/decision`, { body: { decision: "contested" }, key: rkey }))}>
              {f.renter_decision === "contested" ? "Contested" : "Contest"}
            </button>
          </div>
        </div>
      ))}
      {refused.map((f) => (
        <div key={f.id} className="paper line excluded" style={{ marginTop: 14, display: "block" }}>
          <strong>{human(f.part)} — {human(f.damage_class)}</strong>
          <CropPair f={f} />
          <p className="small" style={{ margin: "4px 0 0" }}><strong>{answerText(f)}</strong></p>
        </div>
      ))}
      <Stub r={r} />
      {err ? <div className="toast" role="alert">{err}</div> : null}
      <button className={`btn ${priced.some((f) => f.renter_decision === "accepted") ? "accept" : "release"}`} disabled={!!busy || undecided > 0}
        onClick={() => act("settle", () => api(`/rentals/${r.id}/settle`, { method: "POST", key: rkey }))}>
        {busy === "settle" ? <><span className="spin" /> asking PayPal…</> :
          undecided ? `Decide ${undecided} line${undecided === 1 ? "" : "s"} first` :
            priced.some((f) => f.renter_decision === "accepted")
              ? `Pay ${usd(Math.min(r.deposit_cents, priced.filter((f) => f.renter_decision === "accepted").reduce((s, f) => s + (f.price_cents || 0), 0)))} from the hold · release the rest`
              : "Release the whole hold"}
      </button>
    </div>
  );
}

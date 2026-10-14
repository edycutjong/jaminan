"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Bar from "@/components/Bar";
import Stub from "@/components/Stub";
import { RenterBaseline } from "@/components/flows/Baseline";
import Receipt from "@/components/flows/Receipt";
import RenterSettle from "@/components/flows/RenterSettle";
import { ApiError, adoptUrlKey, api, human, keyFor, usd } from "@/lib/api";
import { useRental } from "@/lib/useRental";

export default function RenterRental() {
  const { id } = useParams<{ id: string }>();
  const [rkey, setRkey] = useState<string | null>(null);
  useEffect(() => { adoptUrlKey(id); setRkey(keyFor(id, "renter")); }, [id]);
  const { r, setR, err } = useRental(id, rkey, ["APPROVED", "OUT", "HELD", "RETURNED", "CLAIMED"]);
  const [busy, setBusy] = useState(false);
  const [perr, setPerr] = useState<string | null>(null);
  const [showTariff, setShowTariff] = useState(false);
  if (err) return <main className="wrap"><Bar who="Renter" /><div className="toast">{err}</div></main>;
  if (!r) return <main className="wrap"><Bar who="Renter" /><div className="skeleton" style={{ marginTop: 20 }} /></main>;
  if (r.role !== "renter") return <main className="wrap"><Bar who="Renter" /><div className="toast">Open this rental from the shop&apos;s QR code — it carries your key.</div><Stub r={r} /></main>;
  const pay = async () => {
    setBusy(true); setPerr(null);
    try { const x = await api(`/rentals/${r.id}/approve`, { method: "POST", key: rkey }); window.location.href = x.approve_url; }
    catch (e) { setPerr(e instanceof ApiError ? e.message : String(e)); setBusy(false); }
  };
  return (
    <main className="wrap">
      <Bar who="Renter" />
      {r.state === "DRAFT" ? (
        <>
          <h1>Ride with your passport in your pocket</h1>
          <p className="muted" style={{ marginTop: 0 }}>{r.vehicle_label} · {r.days} day{r.days === 1 ? "" : "s"} · Demo shop, Jakarta</p>
          <Stub r={r} />
          <div className="note small">
            One PayPal approval: {usd(r.fee_cents)} rental fee is taken at handover; {usd(r.deposit_cents)} is <strong>held, not charged</strong>, and released when you return the scooter — minus only damage you accept.
          </div>
          <p className="small" style={{ marginTop: 12 }}>
            <strong>Saved PayPal:</strong> Save PayPal with this shop for later traffic fines tied to this rental and future rentals, and to renew this rental&apos;s deposit hold if it runs past 3 days; remove it any time from your receipt — if you remove it, fines arrive as an invoice.
          </p>
          <button className="btn ghost sm" onClick={() => setShowTariff((x) => !x)} aria-expanded={showTariff}>Published tariff {r.tariff.id} · sha256 {r.tariff.sha256.slice(0, 12)}</button>
          {showTariff ? (
            <div className="paper" style={{ marginTop: 8 }}>
              <p className="small muted" style={{ marginTop: 0 }}>{r.tariff.status}</p>
              {r.tariff.lines.map((l) => <div key={`${l.part}${l.damage_class}`} className="line"><span>{human(l.part)} — {human(l.damage_class)}</span><span className="price">{usd(l.price_cents)}</span></div>)}
            </div>
          ) : null}
          <button className="btn paypal" style={{ marginTop: 16 }} onClick={pay} disabled={busy}>{busy ? <span className="spin" /> : "Approve with PayPal"}</button>
          {perr ? <div className="toast" role="alert">{perr}</div> : null}
          <p className="small muted">PayPal sandbox. You approve on PayPal&apos;s own page.</p>
        </>
      ) : r.state === "APPROVED" ? (
        <RenterBaseline r={r} rkey={rkey!} onChange={setR} />
      ) : r.state === "OUT" || r.state === "HELD" ? (
        <>
          <h1>Enjoy the ride</h1>
          <Stub r={r} />
          <p className="small data">OUT · tracking {r.tracking_number}</p>
          <p className="small">Bring the scooter back to the shop. The return walkaround happens on the shop&apos;s phone; you settle here.</p>
        </>
      ) : r.state === "RETURNED" || r.state === "CLAIMED" ? (
        <>
          <h1>The shop is checking the return</h1>
          <Stub r={r} />
          <p className="small muted"><span className="spin" /> Any mark the shop points at is checked against the pickup photos you confirmed together.</p>
        </>
      ) : r.state === "PROPOSED" ? (
        <RenterSettle r={r} rkey={rkey!} onChange={setR} />
      ) : (
        <Receipt r={r} rkey={rkey} onChange={setR} />
      )}
      {["DRAFT", "SETTLED", "RELEASED", "INVOICED", "CLOSED"].includes(r.state) ? null : <p className="small" style={{ marginTop: 24 }}><Link href={`/r/${r.id}/evidence`}>Evidence pack</Link></p>}
    </main>
  );
}

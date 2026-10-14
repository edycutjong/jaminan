"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import Stub from "@/components/Stub";
import { ApiError, Rental, api, usd } from "@/lib/api";

export default function Receipt({ r, rkey, onChange }: { r: Rental; rkey: string | null; onChange: (r: Rental) => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [fines, setFines] = useState<any[]>([]);
  useEffect(() => { if (r.fines?.length) api(`/rentals/${r.id}/fines`).then((x) => setFines(x.fines)).catch(() => {}); }, [r.id, r.fines]);
  const st = r.settlement;
  const revoke = async () => {
    try { onChange(await api(`/rentals/${r.id}/vault`, { method: "DELETE", key: rkey })); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  };
  return (
    <div>
      <h1>Receipt</h1>
      <Stub r={r} />
      <dl className="kv">
        <dt>Authorization</dt><dd>{r.authorization_id}</dd>
        <dt>PayPal says</dt><dd>{st?.auth_read_back}</dd>
        {st?.capture_id ? <><dt>Damage capture</dt><dd>{st.capture_id}</dd></> : null}
        <dt>Fee capture</dt><dd>{r.fee_capture_id}</dd>
        <dt>Handover</dt><dd>{r.tracking_number}</dd>
        <dt>Baseline</dt><dd>sha256 {r.baseline_sha256?.slice(0, 16)}…</dd>
      </dl>
      {r.invoice ? (
        <div className="paper" style={{ marginTop: 14 }}>
          <div className="label">Itemized invoice</div>
          <p className="small" style={{ margin: "4px 0" }}>{r.invoice.items.map((i: any) => `${i.name} ${usd(i.amount_cents)}`).join(" · ")}</p>
          {r.invoice.payer_link ? <a href={r.invoice.payer_link} target="_blank" rel="noreferrer">Open the invoice on PayPal</a> : <span className="small muted data">{r.invoice.id}</span>}
          {r.invoice.qr_png_b64 ? <img src={`data:image/png;base64,${r.invoice.qr_png_b64}`} alt="invoice QR" width={160} height={160} style={{ marginTop: 8 }} /> : null}
        </div>
      ) : null}
      {fines.map((f) => (
        <div key={f.id} className="paper" style={{ marginTop: 14 }}>
          <div className="label">Traffic fine {f.id}</div>
          <p className="small">{f.quote?.reason} · {usd(f.quote?.amount_cents)} · {f.status}{f.status === "notified" ? ` · contest until ${f.contest_until?.slice(0, 16)}` : ""}</p>
          {f.status === "notified" && rkey ? <button className="btn ghost sm" onClick={async () => { await api(`/rentals/${r.id}/fines/${f.id}/contest`, { method: "POST", key: rkey }); setFines((x) => x.map((y) => y.id === f.id ? { ...y, status: "contested_invoiced" } : y)); }}>Contest → invoice instead</button> : null}
        </div>
      ))}
      <p style={{ marginTop: 16 }}><Link href={`/r/${r.id}/evidence`}>Evidence pack</Link> · <Link href={`/integrations/verify?rental=${r.id}`}>PayPal calls + read-back</Link></p>
      {rkey && r.vault_id ? (
        <div className="paper" style={{ marginTop: 14 }}>
          <div className="label">Saved PayPal</div>
          {r.vault_revoke ? (
            r.vault_revoke.shown_only
              ? <p className="small">This judge rental uses a shared sandbox wallet, so this button shows the request instead of sending it: <span className="data">{r.vault_revoke.request.method} {r.vault_revoke.request.path}</span></p>
              : <p className="small">Removed (PayPal {r.vault_revoke.status}). Later fines arrive as an invoice.</p>
          ) : (
            <>
              <p className="small">Saved with this shop for later traffic fines tied to this rental. Remove it any time — if you remove it, fines arrive as an invoice.</p>
              <button className="btn ghost" onClick={revoke}>Remove saved PayPal</button>
            </>
          )}
        </div>
      ) : null}
      {err ? <div className="toast" role="alert">{err}</div> : null}
    </div>
  );
}

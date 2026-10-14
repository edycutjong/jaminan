"use client";
import { useEffect, useState } from "react";
import Bar from "@/components/Bar";
import { api } from "@/lib/api";

export default function Verify() {
  const [rental, setRental] = useState<string | null>(null);
  const [d, setD] = useState<any>(null);
  useEffect(() => { setRental(new URL(window.location.href).searchParams.get("rental")); }, []);
  useEffect(() => {
    let alive = true;
    const tick = () => api(`/integrations/verify${rental ? `?rental=${encodeURIComponent(rental)}` : "?readback=false"}`)
      .then((x) => alive && setD(x)).catch(() => {});
    tick();
    const t = setInterval(tick, 4000);
    return () => { alive = false; clearInterval(t); };
  }, [rental]);
  const calls = [...(d?.calls || [])].reverse();
  return (
    <main className="wrap wide">
      <Bar who="PayPal integration" />
      <h1>Every PayPal call{rental ? ` · ${rental}` : ""}</h1>
      <p className="muted" style={{ marginTop: 0 }}>Live from the service ledger: action, object id, HTTP status and PayPal-Debug-Id. The read-back column re-asks PayPal for the authorization — PayPal&apos;s side, not ours.</p>
      {d?.read_back ? (
        <div className="note">Read-back now: <span className="data">{d.read_back.authorization_id}</span> → <strong className={["VOIDED", "CAPTURED"].includes(d.read_back.status) ? "st-ok" : "st-held"}>{d.read_back.status}</strong> <span className="data small">(debug {d.read_back.debug_id})</span></div>
      ) : null}
      <div className="table-wrap" style={{ marginTop: 12 }}><table>
        <thead><tr><th>At (UTC)</th><th>Rental</th><th>Action</th><th>HTTP</th><th>Object id</th><th>PayPal-Debug-Id</th><th>ms</th></tr></thead>
        <tbody>{calls.map((c: any, i: number) => (
          <tr key={i}><td className="data">{c.at?.slice(5, 19).replace("T", " ")}</td><td className="data">{c.rental_id || "—"}</td><td>{c.action}</td>
            <td className={c.http_status < 300 ? "st-ok" : "st-bad"}>{c.http_status}{c.issue ? ` ${c.issue}` : ""}</td>
            <td className="data">{c.object_id || "—"}</td><td className="data">{c.debug_id || "—"}</td><td className="data">{c.ms}</td></tr>
        ))}</tbody>
      </table></div>
      {!calls.length ? <p className="muted small">{d ? "No calls yet." : "loading…"}</p> : null}
      <h2>Webhooks received</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>Received</th><th>Event</th><th>Resource</th><th>Status</th><th>Signature</th></tr></thead>
        <tbody>{[...(d?.webhooks || [])].reverse().map((w: any, i: number) => (
          <tr key={i}><td className="data">{w.received_at?.slice(5, 19).replace("T", " ")}</td><td>{w.event_type}</td><td className="data">{w.resource_id}</td><td>{w.status}</td>
            <td className={w.verified ? "st-ok" : "st-bad"}>{w.verified === null ? "not checked" : w.verified ? "verified" : "failed"}</td></tr>
        ))}</tbody>
      </table></div>
    </main>
  );
}

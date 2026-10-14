"use client";
import { useEffect, useState } from "react";
import Bar from "@/components/Bar";
import { api } from "@/lib/api";

export default function Close() {
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [d, setD] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setBusy(true); setD(null); api(`/close?date=${date}`).then(setD).catch((e) => setD({ error: String(e) })).finally(() => setBusy(false)); }, [date]);
  return (
    <main className="wrap">
      <Bar who="Toko · Shop" />
      <h1>Tutup buku</h1>
      <p className="caption-en" style={{ marginTop: 0 }}>Daily close — our ledger against PayPal Transaction Search</p>
      <input type="date" className="btn ghost" value={date} onChange={(e) => setDate(e.target.value)} aria-label="date" />
      {busy ? <p className="small muted"><span className="spin" /> bertanya ke PayPal…</p> : null}
      {d?.summary ? (
        <>
          <p className="amount" style={{ marginBottom: 0 }}>{d.summary.match} · cocok</p>
          <p className="small muted" style={{ marginTop: 0 }}>{d.summary.pending} menunggu (Transaction Search bisa terlambat beberapa jam) · {d.summary.mismatch} tidak cocok
            <br /><span className="caption-en">{d.summary.match} match PayPal · {d.summary.pending} pending (search lags) · {d.summary.mismatch} mismatch</span></p>
          <div className="table-wrap"><table>
            <thead><tr><th>Sewa</th><th>Jenis</th><th>PayPal id</th><th>Status</th></tr></thead>
            <tbody>{d.rows.map((x: any, i: number) => (
              <tr key={i}><td className="data">{x.rental}</td><td>{x.kind}</td><td className="data">{x.id}</td>
                <td className={x.match === "match" ? "st-ok" : x.match === "pending" ? "st-held" : "st-bad"}>{x.match}</td></tr>
            ))}</tbody>
          </table></div>
          <p className="small muted">Transaction Search HTTP {d.transaction_search_status}{d.transaction_search_issue ? ` · ${d.transaction_search_issue}` : ""} · {d.listed} transaksi tercatat</p>
        </>
      ) : d?.error ? <div className="toast">{d.error}</div> : null}
    </main>
  );
}

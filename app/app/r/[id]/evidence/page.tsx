"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Bar from "@/components/Bar";
import { api, frameUrl, human, keyFor, usd } from "@/lib/api";

export default function Evidence() {
  const { id } = useParams<{ id: string }>();
  const [e, setE] = useState<any>(null);
  useEffect(() => {
    const t = new URL(window.location.href).searchParams.get("t");
    const key = keyFor(id, "renter") || keyFor(id, "shop");
    api(`/rentals/${id}/evidence${t ? `?t=${encodeURIComponent(t)}` : ""}`, { key }).then(setE).catch((x) => setE({ error: x.message || String(x) }));
  }, [id]);
  if (!e) return <main className="wrap"><Bar /><div className="skeleton" style={{ marginTop: 20 }} /></main>;
  if (e.error) return <main className="wrap"><Bar /><div className="toast">{e.error}</div></main>;
  return (
    <main className="wrap wide">
      <Bar who="Evidence pack" />
      <h1>Evidence · {e.rental}</h1>
      <dl className="kv">
        <dt>Tariff</dt><dd>{e.tariff_version} · sha256 {e.tariff_sha256}</dd>
        <dt>Baseline</dt><dd>sha256 {e.baseline_sha256 || "—"}</dd>
        <dt>Handover</dt><dd>{e.tracking_number || "—"}</dd>
        <dt>Benchmarked model</dt><dd>{e.benchmarked_model || "none pinned yet — no line can be charged from the hold"}</dd>
      </dl>
      <h2>Pickup frames (hashed at capture)</h2>
      <div className="angles">{Object.entries(e.pickup).map(([a, p]: any) => (
        p.sha256 ? (
          <a key={a} className="angle done" href={frameUrl(p.sha256)} style={{ backgroundImage: `url(${frameUrl(p.sha256)})` }}>
            <span>{a} · {p.sha256.slice(0, 8)}</span></a>
        ) : <div key={a} className="angle" style={{ cursor: "default" }}><span>{a} · placeholder</span></div>
      ))}</div>
      <h2>Lines</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>Line</th><th>Claim</th><th>Model answer</th><th>Disposition</th><th>Price</th><th>Renter</th><th>Model · request</th></tr></thead>
        <tbody>{e.findings.map((f: any) => (
          <tr key={f.id}><td className="data">{f.id} · {f.angle}</td><td>{human(f.part)} — {human(f.damage_class)} ({f.source})</td>
            <td className="small">{f.mark_at_return == null ? "—" : `mark ${f.mark_at_return} · class ${f.class_consistent} · at pickup ${f.visible_at_pickup} · comparable ${f.pickup_comparable} · same view ${f.same_view} · conf ${f.confidence}`}</td>
            <td>{human(f.disposition)}<br /><span className="small muted">{f.reason}</span></td><td className="data">{usd(f.price_cents)}</td><td>{f.renter_decision || "—"}</td>
            <td className="data">{f.model || "—"}<br />{f.model_request_id || ""}</td></tr>
        ))}</tbody>
      </table></div>
      <h2>PayPal calls</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>At</th><th>Action</th><th>HTTP</th><th>Object</th><th>PayPal-Debug-Id</th></tr></thead>
        <tbody>{e.paypal_calls.map((c: any, i: number) => (
          <tr key={i}><td className="data">{c.at?.slice(11, 19)}</td><td>{c.action}</td><td className={c.http_status < 300 ? "st-ok" : "st-bad"}>{c.http_status}{c.issue ? ` ${c.issue}` : ""}</td><td className="data">{c.object_id}</td><td className="data">{c.debug_id}</td></tr>
        ))}</tbody>
      </table></div>
    </main>
  );
}

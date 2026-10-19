"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import Bar from "@/components/Bar";
import QR from "@/components/QR";
import Stub from "@/components/Stub";
import { ApiError, Rental, api, saveKey, usd } from "@/lib/api";

const SHOP = "shop-demo";
const PILL: Record<string, [string, string]> = {
  DRAFT: ["neutral", "menunggu PayPal"], APPROVED: ["held", "ditahan"], HELD: ["held", "ditahan"], OUT: ["held", "jalan"],
  RETURNED: ["held", "kembali"], CLAIMED: ["held", "dicek"], PROPOSED: ["held", "ke penyewa"], SETTLED: ["charged", "selesai"],
  RELEASED: ["released", "dilepas"], INVOICED: ["charged", "faktur"], CLOSED: ["neutral", "tutup"],
};

export default function Counter() {
  const [shop, setShop] = useState<any>(null);
  const [vehicle, setVehicle] = useState("veh-01");
  const [days, setDays] = useState(1);
  const [created, setCreated] = useState<Rental | null>(null);
  const [list, setList] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = () => api(`/shops/${SHOP}/rentals`).then((x) => setList(x.rentals)).catch(() => {});
  useEffect(() => { api(`/shops/${SHOP}`).then(setShop).catch((e) => setErr(String(e))); refresh(); }, []);
  const v = shop?.vehicles.find((x: any) => x.id === vehicle);
  const start = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api<Rental & { shop_key: string }>(`/shops/${SHOP}/rentals`, { body: { vehicle_id: vehicle, days } });
      saveKey(r.id, "shop", r.shop_key);
      setCreated(r); refresh();
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  };
  return (
    <main className="wrap">
      <Bar who="Toko · Shop" />
      <h1>Sewa baru</h1>
      <p className="caption-en" style={{ marginTop: 0 }}>New rental</p>
      {shop ? (
        <div className="stack">
          <label className="label" htmlFor="veh">Motor</label>
          <select id="veh" className="btn ghost" value={vehicle} onChange={(e) => setVehicle(e.target.value)}>
            {shop.vehicles.map((x: any) => <option key={x.id} value={x.id}>{x.label} · {x.plate}</option>)}
          </select>
          <label className="label" htmlFor="days">Hari · days</label>
          <div className="row">
            {[1, 2, 3, 5, 7].map((d) => <button key={d} className={`btn ${d === days ? "" : "ghost"} sm`} aria-pressed={d === days} onClick={() => setDays(d)}>{d}</button>)}
          </div>
          {v ? <p className="small">Biaya {usd(v.daily_fee_cents * days)} · jaminan ditahan {usd(v.deposit_cents)} · tarif <span className="data">{shop.tariff.id} · {shop.tariff.sha256.slice(0, 12)}</span>
            <br /><span className="caption-en">Fee {usd(v.daily_fee_cents * days)} · deposit held {usd(v.deposit_cents)} (placeholder until the shop names it) · tariff is a DRAFT</span></p> : null}
          <button className="btn" onClick={start} disabled={busy}>{busy ? <span className="spin" /> : "Buat QR untuk penyewa"}</button>
        </div>
      ) : <div className="skeleton" />}
      {err ? <div className="toast" role="alert">{err}</div> : null}
      {created ? (
        <div style={{ marginTop: 18 }}>
          <Stub r={created} lang="id" />
          <p className="small" style={{ textAlign: "center" }}>Penyewa memindai ini dengan ponselnya<br /><span className="caption-en">The renter scans this with their own phone</span></p>
          <QR value={created.renter_link!} label="renter QR" />
          <p className="small" style={{ textAlign: "center", wordBreak: "break-all" }}><a href={created.renter_link}>buka di ponsel ini</a> · <Link href={`/app/shop/r/${created.id}`}>layar toko untuk sewa ini</Link></p>
        </div>
      ) : null}
      <h2>Hari ini</h2>
      <p className="caption-en" style={{ marginTop: -6 }}>Today&apos;s stubs</p>
      {list.length === 0 ? <p className="muted small">Belum ada sewa.</p> : null}
      {list.map((x) => (
        <Link key={x.id} href={`/app/shop/r/${x.id}`} className="line" style={{ textDecoration: "none", color: "inherit" }}>
          <span className="what data">{x.id}</span>
          <span><span className={`pill ${(PILL[x.state] || ["neutral"])[0]}`}>{(PILL[x.state] || ["", x.state])[1]}</span></span>
          <span className="why">{x.vehicle_label} · {usd(x.deposit_cents)} {x.settlement ? `· PayPal ${x.settlement.auth_read_back}` : x.auth_status ? `· PayPal ${x.auth_status}` : ""}</span>
        </Link>
      ))}
      <p style={{ marginTop: 16 }}><Link href="/app/shop/close">Tutup buku hari ini · daily close</Link></p>
    </main>
  );
}

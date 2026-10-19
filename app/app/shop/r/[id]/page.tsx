"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Bar from "@/components/Bar";
import QR from "@/components/QR";
import Stub from "@/components/Stub";
import Walkaround from "@/components/Walkaround";
import { ShopBaseline } from "@/components/flows/Baseline";
import ShopReturn from "@/components/flows/ShopReturn";
import { ApiError, api, keyFor, usd } from "@/lib/api";
import { useRental } from "@/lib/useRental";

function FineForm({ rid, skey }: { rid: string; skey: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [idr, setIdr] = useState(250000);
  const [out, setOut] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="paper stack" style={{ marginTop: 14 }}>
      <div className="label">Tilang e-TLE · traffic fine</div>
      <p className="small" style={{ margin: 0 }}>Foto surat tilang → model membaca plat, waktu dan pasal → cocok dengan masa sewa? Jumlah dibatasi plafon pasal; penyewa punya 72 jam untuk keberatan.
        <br /><span className="caption-en">Ticket photo → plate, time and article read → inside the rental window? Amount capped by the article&apos;s ceiling; the renter has 72 h to contest.</span></p>
      <input type="file" accept="image/*" capture="environment" onChange={(e) => setFile(e.target.files?.[0] || null)} aria-label="ticket photo" />
      <label className="small">Jumlah di surat (IDR) <input type="number" value={idr} onChange={(e) => setIdr(+e.target.value)} className="data" style={{ width: 140 }} /></label>
      <button className="btn ghost" disabled={!file || busy} onClick={async () => {
        setBusy(true);
        const f = new FormData(); f.append("file", file!); f.append("ticket_amount_idr", String(idr));
        try { setOut(await api(`/rentals/${rid}/fines`, { form: f, key: skey })); } catch (e) { setOut({ error: e instanceof ApiError ? e.message : String(e) }); } finally { setBusy(false); }
      }}>{busy ? <span className="spin" /> : "Baca tilang"}</button>
      {out ? out.error ? <div className="toast">{out.error}</div> : <p className="small">{out.quote.chargeable ? `Cocok: ${usd(out.quote.amount_cents)} — penyewa diberi tahu, ditarik setelah 72 jam` : `Tidak bisa ditagih: ${out.quote.reason}`} · plat {out.read?.plate || "?"} · {out.read?.violation || "?"}</p> : null}
    </div>
  );
}

export default function ShopRental() {
  const { id } = useParams<{ id: string }>();
  const [skey, setSkey] = useState<string | null | undefined>(undefined);
  useEffect(() => setSkey(keyFor(id, "shop")), [id]);
  const { r, setR, err } = useRental(id, skey, ["DRAFT", "APPROVED", "PROPOSED"]);
  if (err) return <main className="wrap"><Bar who="Toko" /><div className="toast">{err}</div></main>;
  if (!r) return <main className="wrap"><Bar who="Toko" /><div className="skeleton" style={{ marginTop: 20 }} /></main>;
  if (r.role !== "shop") return <main className="wrap"><Bar who="Toko" /><div className="toast">Layar ini butuh kunci toko dari ponsel yang membuat sewa ini.<br /><span className="caption-en">This screen needs the shop key from the phone that created the rental.</span></div><Stub r={r} lang="id" /></main>;
  return (
    <main className="wrap">
      <Bar who="Toko · Shop" />
      {r.state === "DRAFT" ? (
        <>
          <h1>Menunggu persetujuan PayPal</h1>
          <p className="caption-en" style={{ marginTop: 0 }}>Waiting for the renter&apos;s PayPal approval</p>
          <Stub r={r} lang="id" />
          {r.renter_link ? <QR value={r.renter_link} label="renter QR" /> : null}
        </>
      ) : r.state === "APPROVED" ? (
        <ShopBaseline r={r} skey={skey!} onChange={setR} />
      ) : r.state === "OUT" || r.state === "HELD" ? (
        <>
          <h1>Motor sedang jalan</h1>
          <Stub r={r} lang="id" />
          <p className="small data">OUT · tracking {r.tracking_number}</p>
          <h2>Pengembalian · return walkaround</h2>
          <Walkaround r={r} rkey={skey!} phase="return" lang="id" onChange={setR} />
          <button className="btn" style={{ marginTop: 12 }} disabled={Object.keys(r.photos.return).length < 8}
            onClick={async () => setR(await api(`/rentals/${r.id}/return/complete`, { method: "POST", key: skey }))}>Selesai foto kembali · 8/8</button>
          <button className="btn ghost" style={{ marginTop: 10 }} onClick={async () => setR(await api(`/rentals/${r.id}/release`, { method: "POST", key: skey }))}>Lepas jaminan tanpa cek</button>
        </>
      ) : r.state === "RETURNED" || r.state === "CLAIMED" ? (
        <ShopReturn r={r} skey={skey!} onChange={setR} />
      ) : (
        <>
          <h1>{r.state === "PROPOSED" ? "Menunggu penyewa" : "Selesai"}</h1>
          <p className="caption-en" style={{ marginTop: 0 }}>{r.state === "PROPOSED" ? "The renter accepts or contests each line on their own phone" : "Settled — read back from PayPal"}</p>
          <Stub r={r} lang="id" />
          {r.settlement ? <FineForm rid={r.id} skey={skey!} /> : null}
          <p><Link href={`/app/integrations/verify?rental=${r.id}`}>Panggilan PayPal · read-back</Link> · <Link href={`/app/r/${r.id}/evidence`}>paket bukti</Link></p>
        </>
      )}
    </main>
  );
}

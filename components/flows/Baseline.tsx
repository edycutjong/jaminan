"use client";
import { useState } from "react";
import Walkaround from "@/components/Walkaround";
import { ANGLE_NAMES, ApiError, CLASS_ID, Mark, PART_ID, Rental, api, frameUrl, human } from "@/lib/api";

const ALL = [1, 2, 3, 4, 5, 6, 7, 8];

function Thumb({ r, a, lang }: { r: Rental; a: number; lang: "en" | "id" }) {
  const p = r.photos.pickup[String(a)];
  const style = (b: number[]) => ({ left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${b[2] * 100}%`, height: `${b[3] * 100}%` });
  return (
    <figure className="crop" style={{ margin: 0 }}>
      <div style={{ position: "relative" }}>
        {p?.sha256 ? <img src={frameUrl(p.sha256)} alt={`pickup angle ${a}`} style={{ aspectRatio: "4 / 3", objectFit: "cover" }} /> : <div className="skeleton" style={{ aspectRatio: "4 / 3", height: "auto" }} />}
        {(p?.low_tiles || []).map((b, i) => <span key={i} className="box low" style={style(b)} />)}
        {r.baseline_marks.filter((m) => m.angle === a && !m.removed && m.bbox).map((m) => <span key={m.id} className="box excluded" style={style(m.bbox!)} />)}
      </div>
      <figcaption>{a} · {lang === "id" ? ANGLE_NAMES[a].id : ANGLE_NAMES[a].en}{p?.low_tiles?.length ? (lang === "id" ? " · area arsir" : " · hatched areas") : ""}</figcaption>
    </figure>
  );
}

function MarkRow({ m, canRemove, onRemove, lang }: { m: Mark; canRemove: boolean; onRemove: () => void; lang: "en" | "id" }) {
  const by = { model: lang === "id" ? "model" : "model", renter: lang === "id" ? "penyewa" : "you", shop: lang === "id" ? "toko" : "shop" }[m.source] || m.source;
  return (
    <div className={`line ${m.removed ? "excluded" : ""}`}>
      <span className="what">{lang === "id" ? `${PART_ID[m.part] || human(m.part)} — ${CLASS_ID[m.damage_class] || m.damage_class}` : `${human(m.part)} — ${human(m.damage_class)}`}</span>
      <span className="small muted">{lang === "id" ? "sudut" : "angle"} {m.angle} · {by}</span>
      {canRemove && !m.removed ? <span className="why"><button className="btn ghost sm" onClick={onRemove}>{lang === "id" ? "Hapus" : "Not damage — remove"}</button></span> : null}
      {m.removed ? <span className="why">{lang === "id" ? "dihapus penyewa" : "removed by the renter"}</span> : null}
    </div>
  );
}

function AddMark({ r, rkey, lang, onChange }: { r: Rental; rkey: string; lang: "en" | "id"; onChange: (r: Rental) => void }) {
  const [angle, setAngle] = useState(1);
  const [cls, setCls] = useState("scuff");
  const [part, setPart] = useState("side_panel");
  const parts = Array.from(new Set(r.tariff.lines.map((l) => l.part)));
  return (
    <div className="paper stack" style={{ marginTop: 10 }}>
      <div className="label">{lang === "id" ? "Tambah bekas lama" : "Add an existing mark"}</div>
      <div className="row">
        <select aria-label="angle" value={angle} onChange={(e) => setAngle(+e.target.value)} className="btn ghost sm">{ALL.map((a) => <option key={a} value={a}>{a}</option>)}</select>
        <select aria-label="part" value={part} onChange={(e) => setPart(e.target.value)} className="btn ghost sm">{parts.map((p) => <option key={p} value={p}>{lang === "id" ? PART_ID[p] || p : human(p)}</option>)}</select>
        <select aria-label="class" value={cls} onChange={(e) => setCls(e.target.value)} className="btn ghost sm">{Object.keys(CLASS_ID).map((c) => <option key={c} value={c}>{lang === "id" ? CLASS_ID[c] : human(c)}</option>)}</select>
      </div>
      <button className="btn ghost" onClick={async () => onChange(await api(`/rentals/${r.id}/baseline/marks`, { key: rkey, body: { action: "add", mark: { angle, part, damage_class: cls } } }))}>
        {lang === "id" ? "Tambah" : "Add mark"}
      </button>
    </div>
  );
}

/** Renter side: the 8-angle walkaround, the model's pre-marks (only the renter can remove them), confirm. */
export function RenterBaseline({ r, rkey, onChange }: { r: Rental; rkey: string; onChange: (r: Rental) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const shot = ALL.filter((a) => r.photos.pickup[String(a)]).length;
  const premarked = !!(r as any).premark_calls;
  const mine = r.confirmations?.renter;
  const run = async (label: string, fn: () => Promise<Rental>) => {
    setBusy(label); setErr(null);
    try { onChange(await fn()); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(null); }
  };
  return (
    <div>
      <h1>Pickup walkaround</h1>
      <p className="muted" style={{ marginTop: 0 }}>Eight angles, on your phone. These photos are the shared baseline: at return, any mark the shop points at is checked against them, and a mark already visible here cannot be charged.</p>
      {r.retake_requests.length ? <div className="toast">The shop asked for a retake of angle {r.retake_requests.map((x) => x.angle).join(", ")} — marks in glare or blur there can&apos;t be charged later.</div> : null}
      {shot < 8 || r.retake_requests.length ? <Walkaround r={r} rkey={rkey} phase="pickup" lang="en" onChange={onChange} /> : (
        <>
          <h2>Existing marks</h2>
          {!premarked ? (
            <button className="btn" disabled={!!busy} onClick={() => run("premark", () => api(`/rentals/${r.id}/baseline/premark`, { method: "POST", key: rkey }))}>
              {busy === "premark" ? <><span className="spin" /> the model is listing visible damage…</> : "List the marks already on the scooter"}
            </button>
          ) : (
            <>
              <p className="small muted">The model pre-marks visible damage. Only you can remove one of its marks; the shop can only add.</p>
              {r.baseline_marks.length === 0 ? <p className="small">No existing marks listed.</p> : null}
              {r.baseline_marks.map((m) => <MarkRow key={m.id} m={m} lang="en" canRemove={m.source === "model"}
                onRemove={() => run("rm", () => api(`/rentals/${r.id}/baseline/marks`, { key: rkey, body: { action: "remove", mark: { id: m.id } } }))} />)}
              {r.closeups.map((c) => <p key={c.id} className="small muted">Close-up {c.id} (angle {c.angle}): {c.located === null ? "not checked yet" : c.located ? "located on the photo — it counts" : "could not be located — advisory only"}</p>)}
              <AddMark r={r} rkey={rkey} lang="en" onChange={onChange} />
              <h2>Confirm together</h2>
              <p className="small">You and the shop both confirm this baseline. Then the rental fee is taken from the hold and the rest stays held.</p>
              {mine ? <div className="note">You confirmed. Waiting for the shop…</div> : (
                <button className="btn" disabled={!!busy} onClick={() => run("confirm", () => api(`/rentals/${r.id}/baseline/confirm`, { method: "POST", key: rkey }))}>
                  {busy === "confirm" ? <span className="spin" /> : "I confirm these photos and marks"}
                </button>
              )}
              <div className="angles" style={{ marginTop: 12 }}>{ALL.map((a) => <Thumb key={a} r={r} a={a} lang="en" />)}</div>
            </>
          )}
        </>
      )}
      {err ? <div className="toast" role="alert">{err}</div> : null}
    </div>
  );
}

/** Shop side (Bahasa): see each angle's low-comparability regions, ask for a retake, add marks, confirm. */
export function ShopBaseline({ r, skey, onChange }: { r: Rental; skey: string; onChange: (r: Rental) => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const shot = ALL.filter((a) => r.photos.pickup[String(a)]).length;
  const run = async (fn: () => Promise<Rental>) => {
    setBusy(true); setErr(null);
    try { onChange(await fn()); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  };
  return (
    <div>
      <h1>Foto awal bersama</h1>
      <p className="muted" style={{ marginTop: 0 }}>Penyewa memotret 8 sudut ({shot}/8).<br /><span className="caption-en">The renter is shooting the 8 angles ({shot}/8).</span></p>
      <div className="note small">Area arsir = silau/buram di foto awal: tanda di sana tidak bisa ditagih nanti — minta foto ulang?
        <br /><span className="caption-en">Hatched = glare/blur at pickup: marks there can&apos;t be charged later — ask for a retake?</span></div>
      <div className="crops" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 12 }}>
        {ALL.map((a) => (
          <div key={a}>
            <Thumb r={r} a={a} lang="id" />
            {r.photos.pickup[String(a)]?.low_tiles?.length && !r.retake_requests.some((x) => x.angle === a) ? (
              <button className="btn ghost sm" style={{ width: "100%", marginTop: 4 }} disabled={busy}
                onClick={() => run(() => api(`/rentals/${r.id}/baseline/retake`, { key: skey, body: { angle: a } }))}>Minta foto ulang</button>
            ) : null}
            {r.retake_requests.some((x) => x.angle === a) ? <p className="small muted">menunggu foto ulang</p> : null}
          </div>
        ))}
      </div>
      <h2>Bekas lama</h2>
      {r.baseline_marks.map((m) => <MarkRow key={m.id} m={m} lang="id" canRemove={false} onRemove={() => {}} />)}
      <AddMark r={r} rkey={skey} lang="id" onChange={onChange} />
      <h2>Konfirmasi</h2>
      {r.confirmations?.shop ? <div className="note">Toko sudah konfirmasi. {r.confirmations?.renter ? "" : "Menunggu penyewa…"}</div> : (
        <button className="btn" disabled={busy || shot < 8 || r.retake_requests.length > 0}
          onClick={() => run(() => api(`/rentals/${r.id}/baseline/confirm`, { method: "POST", key: skey }))}>
          {busy ? <span className="spin" /> : "Konfirmasi foto awal · tarik biaya sewa"}
        </button>
      )}
      {err ? <div className="toast" role="alert">{err}</div> : null}
    </div>
  );
}

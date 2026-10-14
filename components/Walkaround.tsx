"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ANGLE_NAMES, ApiError, Rental, api, frameUrl } from "@/lib/api";

const REASON: Record<string, { en: string; id: string }> = {
  blurry: { en: "Blurry — hold still and retake", id: "Buram — tahan dan foto ulang" },
  glare: { en: "Too much glare — step to the side and retake", id: "Terlalu silau — geser sedikit dan foto ulang" },
  too_small: { en: "Frame too small — move closer", id: "Terlalu kecil — dekatkan" },
};

/** Where to stand: a top-down guide (scooter + the camera position for this angle). */
function AngleGuide({ angle }: { angle: number }) {
  const a = ((angle - 1) * 45 - 90) * (Math.PI / 180);
  const cx = 60 + Math.cos(a) * 46, cy = 60 + Math.sin(a) * 46;
  return (
    <svg viewBox="0 0 120 120" width="84" height="84" aria-hidden style={{ position: "absolute", right: 10, top: 10, background: "rgba(243,238,225,.9)", borderRadius: 4 }}>
      <circle cx="60" cy="60" r="46" fill="none" stroke="#CFC5AC" strokeDasharray="3 4" />
      <rect x="51" y="30" width="18" height="60" rx="8" fill="none" stroke="#1C2340" strokeWidth="3" />
      <line x1="44" y1="38" x2="76" y2="38" stroke="#1C2340" strokeWidth="3" />
      <circle cx={cx} cy={cy} r="7" fill="#3346A6" />
      <line x1={cx} y1={cy} x2={60 + (cx - 60) * 0.55} y2={60 + (cy - 60) * 0.55} stroke="#3346A6" strokeWidth="3" />
    </svg>
  );
}

async function toJpeg(canvas: HTMLCanvasElement): Promise<Blob> {
  for (const q of [0.85, 0.75, 0.65, 0.55, 0.45]) {
    const b: Blob | null = await new Promise((res) => canvas.toBlob(res, "image/jpeg", q));
    if (b && (b.size <= 150_000 || q === 0.45)) return b;
  }
  throw new Error("could not encode frame");
}

export default function Walkaround({ r, rkey, phase, lang, onChange }: {
  r: Rental; rkey: string; phase: "pickup" | "return"; lang: "en" | "id"; onChange: (r: Rental) => void;
}) {
  const t = (en: string, id: string) => (lang === "id" ? id : en);
  const video = useRef<HTMLVideoElement>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [camErr, setCamErr] = useState<string | null>(null);
  const done = r.photos[phase] || {};
  const firstMissing = [1, 2, 3, 4, 5, 6, 7, 8].find((a) => !done[String(a)]) ?? 1;
  const [angle, setAngle] = useState<number>(firstMissing);
  const [closeup, setCloseup] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    let s: MediaStream | null = null;
    navigator.mediaDevices?.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1440 } }, audio: false })
      .then((m) => { s = m; setStream(m); if (video.current) { video.current.srcObject = m; video.current.play().catch(() => {}); } })
      .catch((e) => setCamErr(e?.name === "NotAllowedError" ? t("Camera permission denied — allow the camera to take the walkaround.", "Izin kamera ditolak — izinkan kamera untuk foto keliling.") : t("No camera available on this device.", "Kamera tidak tersedia di perangkat ini.")));
    return () => { s?.getTracks().forEach((x) => x.stop()); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const shoot = useCallback(async () => {
    const v = video.current;
    if (!v || !v.videoWidth) return;
    setBusy(true); setToast(null);
    try {
      const c = document.createElement("canvas");
      const w = 1280, h = Math.round((v.videoHeight / v.videoWidth) * 1280);
      c.width = w; c.height = h;
      c.getContext("2d")!.drawImage(v, 0, 0, w, h);
      const blob = await toJpeg(c);
      const form = new FormData();
      form.append("phase", closeup ? "pickup_closeup" : phase);
      form.append("angle", String(angle));
      form.append("file", blob, `angle-${angle}.jpg`);
      const res = await api(`/rentals/${r.id}/photos`, { form, key: rkey });
      if (!res.accepted) {
        const why = REASON[res.gate.reason] || { en: res.gate.reason, id: res.gate.reason };
        setToast({ ok: false, text: lang === "id" ? why.id : why.en });
      } else {
        setToast({ ok: true, text: closeup ? t("Close-up saved — it is part of the shared baseline.", "Foto dekat disimpan.") : `${t("Angle", "Sudut")} ${angle} ✓ · sha256 ${res.photo.sha256.slice(0, 8)}` });
        const fresh = await api<Rental>(`/rentals/${r.id}`, { key: rkey });
        onChange(fresh);
        setCloseup(false);
        const next = [1, 2, 3, 4, 5, 6, 7, 8].find((a) => a !== angle && !fresh.photos[phase][String(a)]);
        if (next && !closeup) setAngle(next);
      }
    } catch (e) {
      setToast({ ok: false, text: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }, [angle, closeup, phase, r.id, rkey, lang, onChange]); // eslint-disable-line react-hooks/exhaustive-deps

  const name = ANGLE_NAMES[angle];
  return (
    <div className="stack">
      <div className="cam">
        <video ref={video} playsInline muted aria-label="camera preview" />
        <div className="overlay">
          <span className="angle-name">{closeup ? t("Close-up of an existing mark", "Foto dekat bekas lama") + ` · ${angle}` : `${angle} · ${lang === "id" ? name.id : name.en}`}</span>
          {!closeup ? <AngleGuide angle={angle} /> : null}
          <svg viewBox="0 0 100 133" preserveAspectRatio="none" style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} aria-hidden>
            <rect x="8" y="14" width="84" height="105" fill="none" stroke="#F3EEE1" strokeWidth="0.6" strokeDasharray="2 2" />
            <line x1="8" y1="104" x2="92" y2="104" stroke="#F3EEE1" strokeWidth="0.5" />
          </svg>
        </div>
        {camErr ? <div className="toast" style={{ position: "absolute", left: 10, right: 10, bottom: 10 }}>{camErr}</div> : null}
      </div>
      <button className="shutter" onClick={shoot} disabled={busy || !stream} aria-label={t("Take photo", "Ambil foto")} />
      {busy ? <p className="muted small" style={{ textAlign: "center" }}><span className="spin" /> {t("checking the frame…", "memeriksa foto…")}</p> : null}
      {toast ? <div className={`toast ${toast.ok ? "ok-toast" : ""}`} role="status">{toast.text}</div> : null}
      <div className="angles" role="list">
        {[1, 2, 3, 4, 5, 6, 7, 8].map((a) => {
          const p = done[String(a)];
          return (
            <button key={a} role="listitem" className={`angle ${p ? "done" : ""} ${a === angle ? "current" : ""}`}
              style={p?.sha256 ? { backgroundImage: `url(${frameUrl(p.sha256)})` } : undefined}
              onClick={() => setAngle(a)} aria-label={`${t("angle", "sudut")} ${a}${p ? " done" : ""}`}>
              <span>{a}{p ? " ✓" : ""}</span>
            </button>
          );
        })}
      </div>
      {phase === "pickup" ? (
        <button className="btn ghost" onClick={() => setCloseup((c) => !c)}>
          {closeup ? t("Back to the 8 angles", "Kembali ke 8 sudut") : t(`Close up an existing mark on angle ${angle}`, `Foto dekat bekas lama di sudut ${angle}`)}
        </button>
      ) : null}
      {phase === "pickup" && r.closeups.length ? <p className="small muted">{r.closeups.length} {t("close-up(s) of existing marks saved", "foto dekat tersimpan")}</p> : null}
    </div>
  );
}

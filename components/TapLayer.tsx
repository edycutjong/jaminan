"use client";
import { useRef, useState } from "react";
import { Rental, Suggestion, frameUrl } from "@/lib/api";

/** The shop's return frame: tap (or drag) to box a mark; dashed boxes are the model's SUGGESTED taps. */
export default function TapLayer({ r, angle, onTap, onSuggestion, pending }: {
  r: Rental; angle: number; pending: number[] | null;
  onTap: (bbox: number[]) => void; onSuggestion: (s: Suggestion) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const [drag, setDrag] = useState<number[] | null>(null);
  const ret = r.photos.return[String(angle)];
  const pick = r.photos.pickup[String(angle)];
  const rel = (e: React.PointerEvent) => {
    const b = ref.current!.getBoundingClientRect();
    return { x: Math.min(Math.max((e.clientX - b.left) / b.width, 0), 1), y: Math.min(Math.max((e.clientY - b.top) / b.height, 0), 1) };
  };
  const down = (e: React.PointerEvent) => { if ((e.target as HTMLElement).closest(".suggested")) return; start.current = rel(e); (e.target as HTMLElement).setPointerCapture?.(e.pointerId); };
  const move = (e: React.PointerEvent) => {
    if (!start.current) return;
    const p = rel(e), s = start.current;
    setDrag([Math.min(s.x, p.x), Math.min(s.y, p.y), Math.abs(p.x - s.x), Math.abs(p.y - s.y)]);
  };
  const up = (e: React.PointerEvent) => {
    if (!start.current) return;
    const p = rel(e), s = start.current;
    start.current = null; setDrag(null);
    let box = [Math.min(s.x, p.x), Math.min(s.y, p.y), Math.abs(p.x - s.x), Math.abs(p.y - s.y)];
    if (box[2] < 0.04 || box[3] < 0.04) box = [Math.max(0, p.x - 0.06), Math.max(0, p.y - 0.08), 0.12, 0.16];
    onTap(box.map((v) => Math.round(v * 10000) / 10000));
  };
  const style = (b: number[]) => ({ left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${b[2] * 100}%`, height: `${b[3] * 100}%` });
  const sugg = r.suggestions.filter((s) => s.angle === angle && s.status === "shown");
  const found = r.findings.filter((f) => f.angle === angle);
  return (
    <div>
      <div ref={ref} className="frame" onPointerDown={down} onPointerMove={move} onPointerUp={up} role="application"
        aria-label="Return photo — tap the mark you want to charge">
        {ret?.sha256 ? <img src={frameUrl(ret.sha256)} alt={`return photo, angle ${angle}`} draggable={false} /> : <div className="skeleton" style={{ height: 240 }} />}
        {(pick?.low_tiles || []).map((b, i) => <span key={`l${i}`} className="box low" style={style(b)} title="low comparability at pickup" />)}
        {found.map((f) => <span key={f.id} className={`box ${f.disposition === "chargeable" ? "" : "excluded"}`} style={style(f.bbox_return)} />)}
        {sugg.map((s) => (
          <button key={s.id} className="box suggested" style={{ ...style(s.bbox_return), background: "transparent" }}
            onClick={() => onSuggestion(s)} aria-label={`suggested: ${s.part} ${s.damage_class}`}>
            <span className="tag">Saran · {s.part.replace(/_/g, " ")}</span>
          </button>
        ))}
        {drag ? <span className="box" style={style(drag)} /> : null}
        {pending && !drag ? <span className="box" style={{ ...style(pending), borderStyle: "dotted" }} /> : null}
      </div>
    </div>
  );
}

"use client";
import { Finding, frameUrl } from "@/lib/api";

export default function CropPair({ f, lang = "en" }: { f: Finding; lang?: "en" | "id" }) {
  const box = (outer: number[] | undefined, inner: number[] | null | undefined, cls: string) => {
    if (!outer || !inner) return null;
    const [ox, oy, ow, oh] = outer;
    const [x, y, w, h] = inner;
    return (
      <span className={`box ${cls}`} style={{ left: `${((x - ox) / ow) * 100}%`, top: `${((y - oy) / oh) * 100}%`, width: `${(w / ow) * 100}%`, height: `${(h / oh) * 100}%` }} />
    );
  };
  return (
    <div className="crops">
      <figure className="crop" style={{ margin: 0 }}>
        <div style={{ position: "relative" }}>
          {f.pickup_sha256 ? <img alt="pickup crop" src={frameUrl(f.pickup_sha256, f.pickup_region)} /> : null}
          {box(f.pickup_region, f.bbox_pickup, "excluded")}
        </div>
        <figcaption>{lang === "id" ? "Saat ambil" : "At pickup"}</figcaption>
      </figure>
      <figure className="crop" style={{ margin: 0 }}>
        <div style={{ position: "relative" }}>
          {f.return_sha256 ? <img alt="return crop" src={frameUrl(f.return_sha256, f.return_region)} /> : null}
          {box(f.return_region, f.bbox_return, f.disposition === "chargeable" ? "" : "excluded")}
        </div>
        <figcaption>{lang === "id" ? "Saat kembali" : "At return"}</figcaption>
      </figure>
    </div>
  );
}

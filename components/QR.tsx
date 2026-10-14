"use client";
import QRCode from "qrcode";
import { useEffect, useState } from "react";

export default function QR({ value, label }: { value: string; label: string }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    QRCode.toDataURL(value, { margin: 1, width: 400, color: { dark: "#1C2340", light: "#FFFFFF" } }).then(setSrc);
  }, [value]);
  return <div className="qr">{src ? <img src={src} alt={label} width={200} height={200} /> : <div className="skeleton" style={{ height: 200 }} />}</div>;
}

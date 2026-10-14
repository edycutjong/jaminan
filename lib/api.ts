"use client";

export type Photo = { sha256: string | null; angle: number; low_tiles?: number[][]; placeholder?: boolean; blur_var?: number; glare_frac?: number };
export type Mark = { id: string; angle: number; part: string; damage_class: string; bbox?: number[] | null; source: string; confirmed?: boolean; removed?: boolean; model?: string };
export type Finding = {
  id: string; angle: number; part: string; damage_class: string; source: string; suggestion_id?: string | null;
  bbox_return: number[]; bbox_pickup?: number[] | null; pickup_region?: number[]; return_region?: number[];
  pickup_sha256: string; return_sha256: string; disposition: string; reason: string; price_cents: number | null;
  tariff_price_cents: number; renter_decision: "accepted" | "contested" | null; model: string | null;
  model_request_id?: string | null; confidence?: number | null; rationale?: string | null; mark_at_return?: boolean | null;
  visible_at_pickup?: boolean | null; pickup_comparable?: boolean | null; class_consistent?: boolean | null; same_view?: boolean | null;
};
export type Suggestion = { id: string; angle: number; part: string; damage_class: string; bbox_return: number[]; status: string; confidence: number; model: string };
export type TariffLine = { part: string; damage_class: string; price_cents: number };
export type Rental = {
  id: string; kind: string; state: string; role?: "shop" | "renter"; shop_id: string; vehicle_label: string; plate: string;
  days: number; fee_cents: number; deposit_cents: number; authorized_cents: number; tariff_version_id: string; tariff_sha256: string;
  order_id?: string; approve_url?: string; authorization_id?: string; auth_status?: string; vault_id?: string; vault_status?: string;
  fee_capture_id?: string; settle_capture_id?: string; baseline_sha256?: string; tracking_number?: string; picked_up_at?: string;
  returned_at?: string; created_at: string; photos: { pickup: Record<string, Photo>; return: Record<string, Photo> };
  closeups: (Photo & { id: string; located: boolean | null; bbox: number[] | null })[];
  baseline_marks: Mark[]; retake_requests: { angle: number; reason: string }[]; confirmations: Record<string, { at: string }>;
  suggestions: Suggestion[]; findings: Finding[]; invoice: any; settlement: any; authorizations: any[]; fines: string[];
  vault_revoke?: any; staged?: any; renter_link?: string; answers: Record<string, string>; benchmarked_model: string | null;
  chargeable_classes: string[]; history: { state: string; at: string }[];
  tariff: { id: string; sha256: string; status: string; lines: TariffLine[]; admin_fee_cents: number; fine_ceilings: any[]; idr_per_usd: number; fx_source: string };
};

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

export function keyFor(rid: string, role: "shop" | "renter"): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(`jaminan:key:${rid}:${role}`);
}

export function saveKey(rid: string, role: "shop" | "renter", key: string) {
  localStorage.setItem(`jaminan:key:${rid}:${role}`, key);
}

/** The renter's key arrives in the QR link (?k=); keep it on this phone and strip it from the address bar. */
export function adoptUrlKey(rid: string): void {
  const u = new URL(window.location.href);
  const k = u.searchParams.get("k");
  if (k) {
    saveKey(rid, "renter", k);
    u.searchParams.delete("k");
    window.history.replaceState(null, "", u.pathname + (u.search ? u.search : "") + u.hash);
  }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: any; key?: string | null; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.key) headers["X-Jaminan-Key"] = opts.key;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
  const res = await fetch(`/api${path}`, { method: opts.method || (body ? "POST" : "GET"), headers, body, cache: "no-store" });
  const text = await res.text();
  let data: any = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { message: text.slice(0, 200) }; }
  if (!res.ok) throw new ApiError(res.status, data.error || "HTTP_" + res.status, data.message || data.detail || res.statusText);
  return data as T;
}

export const usd = (c: number | null | undefined) => (c == null ? "—" : `$${(c / 100).toFixed(2)}`);
export const human = (s: string) => s.replace(/_/g, " ");
export const frameUrl = (sha: string | null | undefined, bbox?: number[] | null, scale = 1) =>
  !sha ? "" : bbox ? `/api/frames/${sha}?bbox=${bbox.map((v) => v.toFixed(4)).join(",")}&scale=${scale}` : `/api/frames/${sha}`;

export const ANGLE_NAMES: Record<number, { en: string; id: string }> = {
  1: { en: "Front", id: "Depan" },
  2: { en: "Front-left", id: "Depan kiri" },
  3: { en: "Left side", id: "Sisi kiri" },
  4: { en: "Rear-left", id: "Belakang kiri" },
  5: { en: "Rear", id: "Belakang" },
  6: { en: "Rear-right", id: "Belakang kanan" },
  7: { en: "Right side", id: "Sisi kanan" },
  8: { en: "Front-right", id: "Depan kanan" },
};

export const PART_ID: Record<string, string> = {
  mirror: "spion", mirror_housing: "rumah spion", indicator_lens: "lampu sein", front_fairing: "body depan",
  side_panel: "body samping", rear_panel: "body belakang", other: "lainnya",
};
export const CLASS_ID: Record<string, string> = {
  missing_part: "hilang", broken_part: "patah", crack: "retak", dent: "penyok", scuff: "baret",
};

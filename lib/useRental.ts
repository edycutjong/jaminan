"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, Rental, api } from "./api";

/** Loads a rental with this phone's key and polls while the other party is acting. */
export function useRental(rid: string, key: string | null, pollStates: string[] = []) {
  const [r, setR] = useState<Rental | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const load = useCallback(async () => {
    try {
      const x = await api<Rental>(`/rentals/${rid}`, { key });
      setR(x); setErr(null);
      return x;
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
      return null;
    }
  }, [rid, key]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!r || !pollStates.includes(r.state)) return;
    timer.current = setTimeout(load, 3000);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [r, load, pollStates]);
  return { r, setR, err, load };
}

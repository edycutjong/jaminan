"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, Rental, api } from "./api";

/** Loads a rental with this phone's key and polls while the other party is acting.
 *  `key === undefined` means "not read from this phone yet" — nothing is fetched until it resolves,
 *  and responses that arrive out of order are dropped. */
export function useRental(rid: string, key: string | null | undefined, pollStates: string[] = []) {
  const [r, setR] = useState<Rental | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const seq = useRef(0);
  const load = useCallback(async () => {
    if (key === undefined) return null;
    const mine = ++seq.current;
    try {
      const x = await api<Rental>(`/rentals/${rid}`, { key });
      if (mine !== seq.current) return null;
      setR(x); setErr(null);
      return x;
    } catch (e) {
      if (mine !== seq.current) return null;
      setErr(e instanceof ApiError ? e.message : String(e));
      return null;
    }
  }, [rid, key]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!r || !pollStates.includes(r.state)) return;
    const timer = setTimeout(load, 3000);
    return () => clearTimeout(timer);
  }, [r, load, pollStates]);
  const set = useCallback((x: Rental) => { seq.current++; setR(x); setErr(null); }, []);
  return { r, setR: set, err, load };
}

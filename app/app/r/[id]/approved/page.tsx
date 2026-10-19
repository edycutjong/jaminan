"use client";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import Bar from "@/components/Bar";
import { ApiError, adoptUrlKey, api, keyFor } from "@/lib/api";

/** PayPal sends the renter back here after the one approval: authorize → the hold exists. */
export default function Approved() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const once = useRef(false);
  useEffect(() => {
    if (once.current) return;
    once.current = true;
    adoptUrlKey(id);
    const key = keyFor(id, "renter");
    api(`/rentals/${id}/authorize`, { method: "POST", key })
      .then((r) => router.replace(r.kind === "judge_full" ? `/app/judge?rental=${id}` : `/app/r/${id}`))
      .catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, [id, router]);
  return (
    <main className="wrap">
      <Bar who="Renter" />
      <h1>Holding the deposit</h1>
      {err ? <div className="toast" role="alert">{err}</div> : <p><span className="spin" /> PayPal approved — creating the hold…</p>}
    </main>
  );
}

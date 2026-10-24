"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import Bar from "@/components/Bar";
import Stub from "@/components/Stub";
import RenterSettle from "@/components/flows/RenterSettle";
import ShopReturn from "@/components/flows/ShopReturn";
import Receipt from "@/components/flows/Receipt";
import { ApiError, Rental, api, keyFor, saveKey } from "@/lib/api";

type Minted = Rental & { shop_key: string; renter_key: string };

function ReadBack({ rid }: { rid: string }) {
  const [rb, setRb] = useState<any>(null);
  useEffect(() => { api(`/integrations/verify?rental=${rid}`).then((x) => setRb(x.read_back)).catch(() => {}); }, [rid]);
  if (!rb) return <p className="small muted"><span className="spin" /> reading the authorization back from PayPal…</p>;
  return (
    <p className="small">PayPal read-back: authorization <span className="data">{rb.authorization_id}</span> is{" "}
      <strong className={rb.status === "VOIDED" || rb.status === "CAPTURED" ? "st-ok" : "st-held"}>{rb.status}</strong>
      {" "}(<span className="data">debug {rb.debug_id}</span>)</p>
  );
}

export default function Judge() {
  const [info, setInfo] = useState<any>(null);
  const [r, setR] = useState<Minted | null>(null);
  const [view, setView] = useState<"shop" | "renter">("shop");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api("/judge/info").then(setInfo).catch(() => setInfo({})); }, []);
  useEffect(() => {
    // the full path comes back here from PayPal: resume the rental with the keys this browser kept
    const id = new URL(window.location.href).searchParams.get("rental");
    const sk = id ? keyFor(id, "shop") : null, rk = id ? keyFor(id, "renter") : null;
    if (!id || !sk || !rk) return;
    api<Rental>(`/rentals/${id}`, { key: sk }).then((x) => setR({ ...x, shop_key: sk, renter_key: rk })).catch((e) => setErr(String(e)));
  }, []);
  const mint = async () => {
    setBusy("mint"); setErr(null);
    try {
      const x = await api<Minted>("/judge", { method: "POST" });
      saveKey(x.id, "shop", x.shop_key); saveKey(x.id, "renter", x.renter_key);
      setR(x); setView("shop");
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(null); }
  };
  const full = async () => {
    setBusy("full"); setErr(null);
    try {
      const x = await api("/judge/full", { method: "POST" });
      saveKey(x.id, "shop", x.shop_key); saveKey(x.id, "renter", x.renter_key);
      window.location.href = x.approve_url;
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); setBusy(null); }
  };
  const merge = (x: Rental) => setR((old) => (old ? { ...old, ...x } : old));
  return (
    <main className="wrap wide">
      <Bar who="Judge" />
      {!r ? (
        <div style={{ maxWidth: 560 }}>
          <h1 style={{ fontSize: 34 }}>{info?.staged_set ? <>You&apos;re the shop — tap what you&apos;d charge</> : <>You&apos;re the shop — hold the deposit, then release it</>}</h1>
          <p>One tap mints a fresh rental on the PayPal sandbox: a merchant-initiated <span className="data">AUTHORIZE</span> of fee + deposit on a saved sandbox wallet, the fee captured from the hold at handover. {info?.staged_set ? "Then you play the shop at the return counter, and the renter at settle." : "Then you release the hold at the return counter, and the stamp waits for PayPal's read-back."}</p>
          {info && !info.staged_set ? (
            <div className="note small">The staged walkaround (real photos of a real scooter, labelled by hand) is not in this deploy yet, and no vision model is pinned by the accuracy bench yet. Until both land, a judge rental shows the real PayPal hold and lets you <strong>release</strong> it; the tap-to-claim screen opens once the staged set ships.</div>
          ) : info && !info.benchmarked_model ? (
            <div className="note small">No vision model is pinned by the accuracy bench yet, so no line you tap can be priced: each one ends <strong>excluded</strong> (it is in the shared baseline) or <strong>comparison unavailable</strong>, and nothing is charged. The model still answers; only a benchmarked model can price a line.</div>
          ) : null}
          <div className="stack" style={{ marginTop: 18 }}>
            <button className="btn" onClick={mint} disabled={!!busy || (info && info.pool === 0)}>{busy === "mint" ? <><span className="spin" /> creating the hold on PayPal…</> : "Start a judge rental"}</button>
            <button className="btn ghost" onClick={full} disabled={!!busy}>{busy === "full" ? <span className="spin" /> : "Full path: approve on the real PayPal page"}</button>
          </div>
          {info?.full_path?.buyer_email ? (
            <p className="small">Full path sandbox buyer login: <span className="data">{info.full_path.buyer_email}</span> / <span className="data">{info.full_path.buyer_password}</span> (PayPal sandbox test account, no real money).</p>
          ) : null}
          {info && info.pool === 0 ? <p className="small muted">Judge wallet pool not configured on this deploy — use the full path.</p> : null}
          {err ? <div className="toast" role="alert">{err} · PayPal&apos;s answers from three recorded sandbox runs: <a href="/#money">on the landing page</a></div> : null}
          <p className="small" style={{ marginTop: 20 }}><Link href="/app/integrations/verify">Every PayPal call, live</Link></p>
        </div>
      ) : (
        <div className="split">
          <div>
            <div className="row" style={{ marginTop: 12 }}>
              <button className={`btn sm ${view === "shop" ? "" : "ghost"}`} aria-pressed={view === "shop"} onClick={() => setView("shop")}>Shop phone</button>
              <button className={`btn sm ${view === "renter" ? "" : "ghost"}`} aria-pressed={view === "renter"} onClick={() => setView("renter")}>Renter phone</button>
            </div>
            {["RETURNED", "CLAIMED"].includes(r.state) && view === "shop" ? (
              <ShopReturn r={r} skey={r.shop_key} onChange={(x) => { merge(x); if (x.state === "PROPOSED") setView("renter"); }} english />
            ) : r.state === "PROPOSED" && view === "renter" ? (
              <RenterSettle r={r} rkey={r.renter_key} onChange={merge} />
            ) : r.settlement && view === "renter" ? (
              <Receipt r={r} rkey={r.renter_key} onChange={merge} />
            ) : (
              <>
                <h1>{r.settlement ? "Settled" : "Hold is live"}</h1>
                <Stub r={r} />
                {!r.settlement && ["OUT", "HELD", "RETURNED", "CLAIMED"].includes(r.state) && view === "renter" ? (
                  <p className="small">Only the shop can release the hold. Switch to the shop phone.</p>
                ) : null}
                {!r.settlement && ["OUT", "HELD", "RETURNED", "CLAIMED"].includes(r.state) && view === "shop" ? (
                  <button className="btn release" disabled={!!busy} onClick={async () => {
                    setBusy("release");
                    try { merge(await api(`/rentals/${r.id}/release`, { method: "POST", key: r.shop_key })); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(null); }
                  }}>{busy === "release" ? <><span className="spin" /> asking PayPal to void…</> : "Release the hold (clean return)"}</button>
                ) : null}
                {r.state === "PROPOSED" && view === "shop" ? <p className="small">Lines sent. Switch to the renter phone to accept or contest.</p> : null}
                {r.settlement && view === "shop" ? <p className="small">Switch to the renter phone for the receipt.</p> : null}
              </>
            )}
            {err ? <div className="toast" role="alert">{err}</div> : null}
          </div>
          <aside className="readback-panel">
            <h2>What PayPal says</h2>
            <ReadBack key={`${r.id}-${r.state}-${r.settlement?.at || ""}`} rid={r.id} />
            <dl className="kv">
              <dt>Rental</dt><dd>{r.id}</dd>
              <dt>Authorization</dt><dd>{r.authorization_id}</dd>
              <dt>Fee capture</dt><dd>{r.fee_capture_id}</dd>
              <dt>Handover</dt><dd>{r.tracking_number}</dd>
              {r.settlement?.capture_id ? <><dt>Final capture</dt><dd>{r.settlement.capture_id}</dd></> : null}
            </dl>
            <p className="small"><Link href={`/app/integrations/verify?rental=${r.id}`}>Full call log with debug ids</Link> · <Link href={`/app/r/${r.id}/evidence`}>evidence pack</Link></p>
            <button className="btn ghost sm" onClick={() => { setR(null); setErr(null); }}>Start another</button>
          </aside>
        </div>
      )}
    </main>
  );
}

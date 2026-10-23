import Link from "next/link";

export const metadata = { title: "Not on this receipt · Jaminan" };

export default function NotFound() {
  return (
    <main className="wrap">
      <a className="brand" href="/">
        <span className="brand-mark" aria-hidden="true">J</span>
        <span className="brand-name">JAMINAN</span>
      </a>
      <p className="label" style={{ marginTop: 40 }}>404 · no such page</p>
      <h1 className="title">Not on this receipt.</h1>
      <p>There is no page at this address. The rule, the money and the judge path are one tap away.</p>
      <div style={{ display: "grid", gap: 12, marginTop: 24 }}>
        <Link className="btn" href="/app/judge">Open the judge path →</Link>
        <a className="btn ghost" href="/">The landing page</a>
        <a className="btn ghost" href="/pitch">Pitch deck</a>
      </div>
    </main>
  );
}

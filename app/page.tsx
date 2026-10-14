import Link from "next/link";
import Bar from "@/components/Bar";

export default function Home() {
  return (
    <main className="wrap">
      <Bar />
      <h1 style={{ fontSize: 34, marginTop: 22 }}>A PayPal hold instead of your passport</h1>
      <p>Scooter shops in Bali and Jakarta keep the renter&apos;s passport as the <em>jaminan</em> — the deposit. At return the owner points at a dent; whoever holds the passport wins.</p>
      <p>Jaminan makes the deposit a PayPal authorization and the argument a shared walkaround. <strong>The owner points, the shared baseline answers.</strong> What the shared baseline can&apos;t show, nobody can charge.</p>
      <div className="stack" style={{ marginTop: 22 }}>
        <Link className="btn" href="/judge">Try it as the shop — /judge</Link>
        <Link className="btn ghost" href="/shop">Shop counter (Bahasa Indonesia)</Link>
        <Link className="btn ghost" href="/integrations/verify">Every PayPal call, live</Link>
      </div>
      <h2>The PayPal lifecycle</h2>
      <ol className="small" style={{ paddingLeft: 20 }}>
        <li>One approval: Orders v2 <span className="data">AUTHORIZE</span> fee + deposit, PayPal saved for later fines.</li>
        <li>Handover: fee captured with <span className="data">final_capture=false</span>; tracking carries the baseline hash.</li>
        <li>Return: accepted lines → one capture with <span className="data">final_capture=true</span>; nothing accepted → <span className="data">void</span>.</li>
        <li>Contested lines → itemized PayPal invoice at the tariff price. Long rentals → reauthorize on day 4.</li>
      </ol>
      <p className="small muted">PayPal sandbox only. The demo uses one sandbox merchant.</p>
    </main>
  );
}

import recorded from "@/evidence/generated-pair/run-2026-10-25.json";
import { GENERATED_LABEL, GeneratedRun, summarize } from "@/lib/generatedPair";

const RUN = recorded as GeneratedRun;
const CLAIMS = summarize(RUN);
const usd = (c: number) => `$${(c / 100).toFixed(2)}`;

function Frame({ src, phase }: { src: string; phase: "pickup" | "return" }) {
  return (
    <figure className="gp-frame">
      <div className="gp-img">
        <img src={src} width={960} height={536} loading="lazy"
          alt={`${GENERATED_LABEL}: the ${phase} frame of a white scooter, front-left view${phase === "return" ? ", edited so both rear-view mirrors are gone" : ", both mirrors on, a grey scuff on the front fairing"}`} />
        {CLAIMS.map((c) => (
          <span key={c.id} className="gp-box" aria-hidden="true"
            style={{ left: `${c.bbox[0] * 100}%`, top: `${c.bbox[1] * 100}%`, width: `${c.bbox[2] * 100}%`, height: `${c.bbox[3] * 100}%` }}>
            <b>{c.id}</b>
          </span>
        ))}
      </div>
      <figcaption>{phase === "pickup" ? "At pickup" : "At return"} · <span className="gp-label">{GENERATED_LABEL}</span></figcaption>
    </figure>
  );
}

export default function GeneratedPair() {
  const pinnedPrice = CLAIMS.find((c) => c.pricedIfPinnedCents)?.pricedIfPinnedCents;
  return (
    <section className="gp" aria-labelledby="gp-h">
      <p className="gp-chip">{GENERATED_LABEL}</p>
      <h2 id="gp-h">Recorded model answers on a generated pair</h2>
      <p className="small">A pickup image made by qwen-image-2.0 and a return image edited from it by wan2.6-image, which removed both
        mirrors. The builder pointed two claims; the app&apos;s own claim path asked <span className="data">{CLAIMS[0].models}</span> three
        times each. These are recorded answers, not a benchmark, and not real-world evidence.</p>
      <div className="gp-pair">
        <Frame src="/site/generated-pair/pickup-front-left.jpg" phase="pickup" />
        <Frame src="/site/generated-pair/return-front-left.jpg" phase="return" />
      </div>
      {CLAIMS.map((c) => (
        <div key={c.id} className="gp-claim">
          <p><b>{c.id}</b> · the shop points: <strong>{c.claim}</strong></p>
          <dl className="kv">
            <dt>True answer</dt><dd>{c.truth}</dd>
            <dt>Model read</dt><dd>{c.read} · <strong className={c.wrong ? "gp-wrong" : "st-ok"}>{c.tally}</strong></dd>
            <dt>Its reason</dt><dd>&ldquo;{c.rationale}&rdquo;</dd>
            <dt>App answer</dt><dd>{c.appAnswer} (no model is benchmarked yet)</dd>
          </dl>
        </div>
      ))}
      {pinnedPrice ? (
        <p className="note small">Had this model been pinned without the bench, the rules would have priced C1 at {usd(pinnedPrice)} from
          the tariff for a scuff that was there at pickup. That is why no model can price a line until it passes a held-out bench on real photos.</p>
      ) : null}
      <p className="small">Recorded {RUN.recorded_at} · <a href="/evidence/generated-pair/README.md">evidence and request ids</a> ·{" "}
        <a href="/evidence/generated-pair/GENERATION.json">how the images were generated</a></p>
    </section>
  );
}

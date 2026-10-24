"use client";
import { Rental, human, usd } from "@/lib/api";

import { answerText } from "@/lib/answers";

export { answerText };

/** The signature element: a perforated kwitansi stub. Stamps are drawn ONLY from PayPal's read-back. */
export default function Stub({ r, lang = "en", children }: { r: Rental; lang?: "en" | "id"; children?: React.ReactNode }) {
  const st = r.settlement;
  const readBack: string | undefined = st?.auth_read_back;
  const confirmed = readBack === "VOIDED" || readBack === "CAPTURED";
  const accepted = new Set<string>(st?.accepted || []);
  const lines = r.findings || [];
  const t = (en: string, id: string) => (lang === "id" ? id : en);
  return (
    <section className="stub" aria-label={`Rental ${r.id} stub`}>
      <div className="stub-head">
        <div>
          <div className="label">{t("Rental", "Sewa")}</div>
          <div className="no">{r.id}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="label">{r.vehicle_label}</div>
          <div className="small data">{r.days} {t(r.days === 1 ? "day" : "days", "hari")}</div>
        </div>
      </div>
      <div className="stub-body">
        <div className="line">
          <span className="what">{t("Rental fee", "Biaya sewa")}</span>
          <span className="price">{usd(r.fee_cents)}</span>
          <span className="why">{r.fee_capture_id ? t("captured from the hold", "ditarik dari jaminan") : t("captured at handover", "ditarik saat serah terima")}</span>
        </div>
        {lines.map((f) => {
          const chargeable = f.disposition === "chargeable";
          const charged = confirmed && accepted.has(f.id);
          return (
            <div key={f.id} className={`line ${chargeable ? (charged ? "charged" : "") : "excluded"}`}>
              <span className="what">{human(f.part)} — {human(f.damage_class)}</span>
              <span className="price">{chargeable ? usd(f.price_cents) : "—"}</span>
              <span className="why">
                {answerText(f, lang)}
                {lang === "id" ? <><br /><span className="caption-en">{answerText(f, "en")}</span></> : null}
                {chargeable && f.renter_decision ? ` · ${f.renter_decision}` : ""}
              </span>
              {charged ? <span className="stamp charged" aria-label="charged">{t("Charged", "Ditagih")}</span> : null}
            </div>
          );
        })}
      </div>
      <div className="perf" aria-hidden />
      <div className="stub-foot">
        <div className="label">{t("Damage deposit", "Jaminan kerusakan")}</div>
        <div className={`amount ${confirmed ? "" : "held"}`}>{usd(r.deposit_cents)}</div>
        <div className="small muted">
          {confirmed
            ? st.void
              ? t("whole hold released", "seluruh jaminan dilepas")
              : `${usd(st.capture_cents)} ${t("captured", "ditarik")} · ${usd(st.released_cents)} ${t("released", "dilepas")}`
            : r.authorization_id
              ? t("held on PayPal — not charged", "ditahan di PayPal — tidak ditagih")
              : t("will be held on PayPal, not charged", "akan ditahan di PayPal, tidak ditagih")}
        </div>
        {confirmed ? (
          <span className="stamp released" role="status">
            Dilepas · Released
            <small>PayPal: {readBack}</small>
          </span>
        ) : r.authorization_id ? (
          <span className="stamp held">Ditahan · Held</span>
        ) : null}
        {children}
      </div>
    </section>
  );
}

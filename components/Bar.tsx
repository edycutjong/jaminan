import Link from "next/link";

export default function Bar({ who }: { who?: string }) {
  return (
    <header className="bar">
      <Link href="/" className="brand" aria-label="Jaminan home">
        <span className="brand-mark" aria-hidden>J</span>
        <span className="brand-name">JAMINAN</span>
      </Link>
      {who ? <span className="who">{who}</span> : null}
    </header>
  );
}

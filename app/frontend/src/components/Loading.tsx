import { useEffect, useState } from "react";

const STEPS = [
  { tx: "Reading your intent", co: "✓ parsed" },
  { tx: "Retrieving candidates", co: "300+ found" },
  { tx: "Scoring & ranking", co: "top 4" },
  { tx: "Verifying reliability", co: "verified" },
];

export function Loading({ query }: { query: string }) {
  const [active, setActive] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setActive((a) => Math.min(STEPS.length, a + 1)), 440);
    return () => clearInterval(id);
  }, []);
  return (
    <section className="max-w-[520px] mx-auto px-6 py-20">
      <div className="font-mono text-[11px] uppercase tracking-wider mb-2" style={{ color: "var(--color-ink3)" }}>Working on it</div>
      <div className="font-display font-bold text-[16px] mb-4 text-balance">{query}</div>
      {STEPS.map((s, i) => {
        const done = i < active, on = i === active - 1 || done;
        return (
          <div key={s.tx} className="flex items-center gap-3.5 py-3 transition-opacity" style={{ opacity: on ? 1 : 0.35 }}>
            <span className="w-[26px] h-[26px] rounded-full flex items-center justify-center font-mono text-[12px] shrink-0 border-2"
              style={{
                borderColor: done ? "var(--color-good)" : on ? "var(--color-accent)" : "var(--color-hairline2)",
                background: done ? "var(--color-good)" : "transparent",
                color: done ? "#fff" : on ? "var(--color-accent)" : "var(--color-ink3)",
              }}>
              {done ? "✓" : i + 1}
            </span>
            <span className="text-[15px]" style={{ color: "var(--color-ink)" }}>{s.tx}</span>
            <span className="ml-auto font-mono text-[12px]" style={{ color: "var(--color-ink3)" }}>{done ? s.co : ""}</span>
          </div>
        );
      })}
      <div className="h-1 rounded mt-5 overflow-hidden" style={{ background: "var(--color-sunk)" }}>
        <div className="h-full rounded" style={{ width: `${(active / STEPS.length) * 100}%`, background: "var(--color-accent)", transition: "width .3s" }} />
      </div>
    </section>
  );
}

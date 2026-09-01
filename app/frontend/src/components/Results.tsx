import { useState } from "react";
import type { SearchResponse } from "../types";
import { ResultCard } from "./ResultCard";

export function Results({ data, onCopy, onPick, onRequireAuth }: {
  data: SearchResponse;
  onCopy: (m: string) => void;
  onPick: (q: string) => void;
  onRequireAuth: () => void;
}) {
  const [openId, setOpenId] = useState<string>(data.results[0]?.id ?? "");
  const { intent, results } = data;

  const tokens: [string, string, boolean][] = [
    ["Purpose", intent.purpose, true],
    ["Type", intent.prompt_type, true],
    ["Goal", intent.query.length > 40 ? intent.query.slice(0, 40) + "…" : intent.query, false],
  ];

  return (
    <section className="max-w-[920px] mx-auto px-6 pt-6 pb-24">
      {/* intent bar */}
      <div className="rounded-[14px] border p-4 mb-4.5" style={{ background: "var(--color-panel)", borderColor: "var(--color-hairline)" }}>
        <div className="text-[15px]" style={{ color: "var(--color-ink2)" }}>
          Your goal: <b style={{ color: "var(--color-ink)" }}>{intent.query}</b>
        </div>
        <div className="flex flex-wrap gap-2 mt-3">
          {tokens.map(([k, v, key]) => (
            <span key={k} className="font-mono text-[11.5px] rounded-lg px-2.5 py-1 border flex gap-1.5 items-center"
              style={{
                background: key ? "var(--color-accentsoft)" : "var(--color-panel2)",
                borderColor: key ? "var(--color-accentline)" : "var(--color-hairline2)",
                color: key ? "var(--color-accent2)" : "var(--color-ink)",
              }}>
              <b style={{ color: key ? "var(--color-accent)" : "var(--color-ink3)", fontWeight: 500 }}>{k}</b>{v}
            </span>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between mx-0.5 mb-3 gap-3 flex-wrap">
        <span className="font-mono text-[12px] uppercase tracking-wider" style={{ color: "var(--color-ink3)" }}>
          {results.length} of {data.count} candidates · ranked by overall fit
        </span>
        <span className="font-mono text-[10.5px] px-2.5 py-1 rounded-full inline-flex items-center gap-1.5"
          style={{
            background: data.enriched ? "var(--color-accentsoft)" : "var(--color-sunk)",
            color: data.enriched ? "var(--color-accent2)" : "var(--color-ink3)",
            border: `1px solid ${data.enriched ? "var(--color-accentline)" : "var(--color-hairline)"}`,
          }}>
          {data.enriched ? "◆ AI-matched to your goal" : "◇ TF-IDF match (add API key for AI matching)"}
        </span>
      </div>

      {results.map((r, i) => (
        <ResultCard key={r.id} r={r} rank={i + 1} open={openId === r.id} onToggle={() => setOpenId(r.id)}
          onCopy={onCopy} onPick={onPick} onRequireAuth={onRequireAuth} />
      ))}

      <p className="font-mono text-[11px] mt-3" style={{ color: "var(--color-ink3)" }}>
        Scores are live from the evaluation API · reliability figures are seeded sample data.
      </p>
    </section>
  );
}

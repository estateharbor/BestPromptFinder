import { useEffect, useState } from "react";
import { api } from "../api";
import type { PromptResult } from "../types";
import { ResultCard } from "./ResultCard";

export function Library({ onCopy, onPick }: { onCopy: (m: string) => void; onPick: (q: string) => void }) {
  const [items, setItems] = useState<PromptResult[] | null>(null);
  const [openId, setOpenId] = useState("");

  useEffect(() => {
    api.library().then((r) => { setItems(r.results); setOpenId(r.results[0]?.id ?? ""); }).catch(() => setItems([]));
  }, []);

  return (
    <section className="max-w-[920px] mx-auto px-6 pt-8 pb-24">
      <h2 className="font-display font-extrabold text-[24px] tracking-tight">Your library</h2>
      <p className="text-[14px] mt-1 mb-6" style={{ color: "var(--color-ink2)" }}>
        Prompts you've saved — private to your account, synced across devices.
      </p>

      {items === null && <p className="font-mono text-[13px]" style={{ color: "var(--color-ink3)" }}>Loading…</p>}
      {items?.length === 0 && (
        <div className="rounded-2xl border p-8 text-center" style={{ background: "var(--color-panel2)", borderColor: "var(--color-hairline)" }}>
          <p className="text-[15px]" style={{ color: "var(--color-ink2)" }}>No saved prompts yet.</p>
          <p className="font-mono text-[12px] mt-2" style={{ color: "var(--color-ink3)" }}>Search, then tap the bookmark on any result to save it here.</p>
        </div>
      )}
      {items?.map((r, i) => (
        <ResultCard key={r.id} r={r} rank={i + 1} open={openId === r.id} onToggle={() => setOpenId(r.id)} onCopy={onCopy} onPick={onPick} />
      ))}
    </section>
  );
}

import { useEffect, useState } from "react";
import { api } from "../api";
import type { LibraryStats } from "../types";

function ago(iso: string | null): string {
  if (!iso) return "—";
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 90) return "just now";
  if (secs < 3600) return `${Math.round(secs / 60)} min ago`;
  if (secs < 172800) return `${Math.round(secs / 3600)} h ago`;
  return `${Math.round(secs / 86400)} days ago`;
}

export function Stats() {
  const [s, setS] = useState<LibraryStats | null>(null);
  useEffect(() => { api.stats().then(setS).catch(() => setS(null)); }, []);
  if (!s) return null;

  const graded = (s.eval_source.llm ?? 0) + (s.eval_source.curated ?? 0);
  const gradedPct = s.total ? Math.round((graded / s.total) * 100) : 0;
  const platforms = Object.entries(s.by_platform).slice(0, 6);
  const maxPlat = Math.max(1, ...platforms.map(([, n]) => n));

  const Metric = ({ big, lab }: { big: string; lab: string }) => (
    <div>
      <div className="font-display font-black text-[26px] leading-none tnum" style={{ color: "var(--color-accent)" }}>{big}</div>
      <div className="font-mono text-[10.5px] uppercase tracking-wide mt-1.5" style={{ color: "var(--color-ink3)" }}>{lab}</div>
    </div>
  );

  return (
    <div className="max-w-[640px] mx-auto mt-6 text-left">
      <div className="rounded-[15px] border p-5" style={{ background: "var(--color-panel)", borderColor: "var(--color-hairline)" }}>
        <div className="flex items-baseline justify-between mb-4">
          <span className="font-display font-extrabold text-[15px] tracking-tight">Library at a glance</span>
          <span className="font-mono text-[11px]" style={{ color: "var(--color-ink3)" }}>updated {ago(s.last_refreshed)}</span>
        </div>

        <div className="grid grid-cols-4 gap-3 max-[520px]:grid-cols-2">
          <Metric big={s.total.toLocaleString()} lab="prompts" />
          <Metric big={`${gradedPct}%`} lab="AI-graded" />
          <Metric big={String(Object.keys(s.by_platform).length)} lab="sources" />
          <Metric big={s.votes.toLocaleString()} lab="user votes" />
        </div>

        <div className="mt-5 pt-4 border-t" style={{ borderColor: "var(--color-hairline)" }}>
          <div className="font-mono text-[10.5px] uppercase tracking-wide mb-3" style={{ color: "var(--color-ink3)" }}>By source</div>
          <div className="flex flex-col gap-2">
            {platforms.map(([name, n]) => (
              <div key={name} className="flex items-center gap-3">
                <span className="text-[12.5px] w-[110px] shrink-0 truncate" style={{ color: "var(--color-ink2)" }}>{name}</span>
                <span className="flex-1 h-[7px] rounded-md overflow-hidden" style={{ background: "var(--color-sunk)" }}>
                  <span className="block h-full rounded-md" style={{ width: `${(n / maxPlat) * 100}%`, background: "var(--color-accent)" }} />
                </span>
                <span className="font-mono text-[11.5px] w-[42px] text-right tnum" style={{ color: "var(--color-ink)" }}>{n}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

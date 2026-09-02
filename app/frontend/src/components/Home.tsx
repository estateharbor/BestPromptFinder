import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { LeaderItem } from "../types";
import { useAuth } from "../auth";
import { Stats } from "./Stats";

// Fallback chips if the leaderboard hasn't loaded yet (or the API is down).
const EXAMPLES = [
  { label: "Earnings: bullish or bearish?", q: "Analyze a company's quarterly results and tell me if they're bullish or bearish" },
  { label: "Facebook real-estate campaign", q: "Create a Facebook campaign for a luxury real-estate project targeting investors" },
  { label: "Midjourney product shot", q: "Midjourney product shot of a luxury watch, cinematic studio lighting" },
];

// Trim a long title into a short, punchy chip label.
function chipLabel(title: string): string {
  const t = title.replace(/\s*[—–|:].*$/, "").trim(); // drop trailing sub-clause
  return t.length > 34 ? t.slice(0, 32).trimEnd() + "…" : t;
}

// Build the "Try" chips: the best prompt in each distinct category. `preferred` is the
// signed-in user's most-saved categories — those lead the list (personalized); the rest
// fill in, lightly shuffled for variety. With no preferences it's just diverse-best.
function pickChips(items: LeaderItem[], n: number, preferred: string[]): { label: string; q: string }[] {
  const bestByCat = new Map<string, LeaderItem>();
  for (const it of items) if (!bestByCat.has(it.purpose)) bestByCat.set(it.purpose, it); // best-first
  const pref = preferred.filter((c) => bestByCat.has(c));            // user's cats we can serve
  const rest = [...bestByCat.keys()].filter((c) => !pref.includes(c));
  for (let i = rest.length - 1; i > 0; i--) {                        // shuffle the filler
    const j = Math.floor(Math.random() * (i + 1));
    [rest[i], rest[j]] = [rest[j], rest[i]];
  }
  return [...pref, ...rest].slice(0, n).map((c) => {
    const it = bestByCat.get(c)!;
    return { label: chipLabel(it.title), q: it.title };
  });
}

function Spark({ vals }: { vals: number[] }) {
  const max = Math.max(...vals), min = Math.min(...vals), rng = max - min || 1;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * 62 + 1},${(24 - ((v - min) / rng) * 20).toFixed(1)}`).join(" ");
  const lx = 63, ly = (24 - ((vals[vals.length - 1] - min) / rng) * 20).toFixed(1);
  return (
    <svg width="64" height="26" viewBox="0 0 64 26" aria-hidden className="max-[560px]:hidden">
      <polyline points={pts} fill="none" stroke="var(--color-good)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={lx} cy={ly} r="2" fill="var(--color-good)" />
    </svg>
  );
}

export function Home({ onSearch, error }: { onSearch: (q: string) => void; error: string | null }) {
  const { user } = useAuth();
  const [q, setQ] = useState("");
  const [focused, setFocused] = useState(false);   // glow the search box only while focused
  const [top, setTop] = useState<LeaderItem[]>([]);
  const [savedCats, setSavedCats] = useState<string[]>([]);

  useEffect(() => {
    api.leaderboard(12).then((r) => setTop(r.results)).catch(() => setTop([]));
  }, []);

  // For a signed-in user, rank the categories they save most — those bias the chips.
  useEffect(() => {
    if (!user) { setSavedCats([]); return; }
    api.library()
      .then((r) => {
        const freq = new Map<string, number>();
        for (const p of r.results) freq.set(p.purpose, (freq.get(p.purpose) ?? 0) + 1);
        setSavedCats([...freq.entries()].sort((a, b) => b[1] - a[1]).map(([c]) => c));
      })
      .catch(() => setSavedCats([]));
  }, [user]);

  // Dynamic "Try" chips from the live best prompts: personalized to the user's saved
  // categories when signed in, diverse-best otherwise. Falls back to static examples
  // until the leaderboard loads.
  const tryChips = useMemo(
    () => (top.length ? pickChips(top, 4, savedCats) : EXAMPLES),
    [top, savedCats]
  );

  const trend = (rel: number) => 5 + (rel % 10);

  return (
    <section className="max-w-[920px] mx-auto px-6 pt-[min(13vh,110px)] pb-16 text-center">
      <div className="font-mono text-[12px] tracking-[0.14em] uppercase" style={{ color: "var(--color-accent2)" }}>
        The prompt decision engine
      </div>
      <h1 className="font-display font-black text-[clamp(30px,5.4vw,52px)] tracking-[-0.035em] mt-4 text-balance">
        Don't search for prompts.
        <br />
        <span style={{ color: "var(--color-accent)" }}>Tell us what you need.</span>
      </h1>
      <p className="mx-auto mt-4 text-[clamp(16px,2vw,18px)] max-w-[46ch]" style={{ color: "var(--color-ink2)" }}>
        Describe a goal in plain words. We rank the prompts most likely to solve it — and show you why before you run one.
      </p>

      <form
        onSubmit={(e) => { e.preventDefault(); onSearch(q); }}
        className="max-w-[620px] mx-auto mt-9 flex items-center gap-3 rounded-[15px] pl-5 pr-1.5 py-1.5 border-2"
        style={{
          borderColor: "var(--color-accent)", background: "var(--color-panel)",
          boxShadow: focused ? "0 0 0 4px color-mix(in srgb, var(--color-accent) 22%, transparent)" : "none",
          transition: "box-shadow .2s ease",
        }}
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          autoFocus
          placeholder="e.g. analyze a company's quarterly results — bullish or bearish?"
          className="flex-1 bg-transparent outline-none text-[17px] py-3"
          style={{ color: "var(--color-ink)" }}
        />
        <button
          type="submit"
          className="font-display font-bold text-[15px] px-5 py-3 rounded-[11px] text-white shrink-0 active:scale-[0.97] transition"
          style={{ background: "var(--color-accent)" }}
        >
          Find prompts
        </button>
      </form>

      {error && <p className="mt-3 font-mono text-[12px]" style={{ color: "var(--color-weak)" }}>{error} — is the API running on :8000?</p>}

      <div className="mt-5 text-left max-w-[620px] mx-auto">
        <span className="font-mono text-[11.5px] mr-1" style={{ color: "var(--color-ink3)" }}>Try:</span>
        {tryChips.map((ex) => (
          <button
            key={ex.label}
            onClick={() => onSearch(ex.q)}
            className="font-mono text-[12px] px-3 py-1.5 rounded-full mr-1.5 mt-1.5 border transition hover:-translate-y-0.5"
            style={{ color: "var(--color-ink2)", background: "var(--color-panel)", borderColor: "var(--color-hairline2)" }}
          >
            {ex.label}
          </button>
        ))}
      </div>

      {/* Top performers (leaderboard) */}
      {top.length > 0 && (
        <div className="max-w-[640px] mx-auto mt-14 text-left">
          <div className="flex items-baseline justify-between mb-3.5">
            <span className="font-display font-extrabold text-[17px] tracking-tight">Top performers this week</span>
            <span className="font-mono text-[11px] uppercase tracking-wider" style={{ color: "var(--color-ink3)" }}>ranked by reliability</span>
          </div>
          <div className="rounded-[15px] border overflow-hidden" style={{ background: "var(--color-panel)", borderColor: "var(--color-hairline)" }}>
            {top.slice(0, 5).map((it, i) => (
              <button
                key={it.id}
                onClick={() => onSearch(it.title)}
                className="w-full text-left grid items-center gap-3.5 px-4 py-3 border-t first:border-t-0 transition hover:bg-[var(--color-panel2)]"
                style={{ borderColor: "var(--color-hairline)", gridTemplateColumns: "26px 1fr auto auto" }}
              >
                <span className="font-mono text-[13px]" style={{ color: "var(--color-ink3)" }}>{i + 1}</span>
                <span>
                  <span className="block font-display font-bold text-[14.5px] tracking-tight">{it.title}</span>
                  <span className="block font-mono text-[10.5px] mt-0.5" style={{ color: "var(--color-ink3)" }}>{it.purpose}</span>
                </span>
                <Spark vals={[70, 74, 72, 80, 84, it.useful - 2, it.useful]} />
                <span className="text-right min-w-[64px]">
                  <span className="block font-display font-extrabold text-[15px] leading-none tnum">{it.useful}%</span>
                  <span className="block font-mono text-[9px] uppercase tracking-wider mt-0.5" style={{ color: "var(--color-ink3)" }}>
                    useful · {it.uses} uses
                  </span>
                  <span className="inline-flex items-center gap-1 font-mono text-[11px] font-medium px-1.5 py-0.5 rounded-full mt-1"
                    style={{ color: "var(--color-good)", background: "var(--color-goodsoft)" }}>▲ {trend(it.reliability)}%</span>
                </span>
              </button>
            ))}
          </div>
          <p className="font-mono text-[10.5px] mt-2" style={{ color: "var(--color-ink3)" }}>
            Reliability figures are seeded sample data — wired to real run telemetry in production.
          </p>
        </div>
      )}

      <Stats />
    </section>
  );
}

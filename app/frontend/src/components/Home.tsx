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

// Show the full prompt title on the chip (only clip pathologically long ones).
function chipLabel(title: string): string {
  const t = title.trim();
  return t.length > 72 ? t.slice(0, 70).trimEnd() + "…" : t;
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

// The main categories, with slugs matching the backend's slugify(), rendered as real
// <a> links so crawlers (and AI answer engines) can follow them to the server-rendered
// category pages — the homepage's primary actions are otherwise JS buttons.
const CATEGORIES: { name: string; slug: string }[] = [
  { name: "Coding", slug: "coding" },
  { name: "Writing", slug: "writing" },
  { name: "Image Generation", slug: "image-generation" },
  { name: "Graphic Design", slug: "graphic-design" },
  { name: "Financial Analysis", slug: "financial-analysis" },
  { name: "Data / Analysis", slug: "data-analysis" },
  { name: "Research", slug: "research" },
  { name: "Education", slug: "education" },
  { name: "Roleplay", slug: "roleplay" },
];

const FAQ: { q: string; a: string }[] = [
  { q: "What is BestPromptFinder?", a: "A free prompt decision engine: instead of browsing a directory, you describe your goal in plain words and it ranks the prompts most likely to solve it — showing quality, goal-match and confidence before you run one." },
  { q: "Which AI models do the prompts work with?", a: "ChatGPT, Claude, Google Gemini and Midjourney, across categories like coding, marketing, finance, SEO, image generation, research and education." },
  { q: "How are the prompts rated?", a: "An AI evaluator grades each prompt on usefulness, clarity, structure and reusability. Confidence starts as that estimate and is refined over time by real 'worked / didn't work' votes from users." },
  { q: "Is BestPromptFinder free?", a: "Yes. Searching and using prompts is free. You can create an account to save prompts to a private library." },
];

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

      <div className="mt-6 max-w-[760px] mx-auto flex flex-wrap items-center justify-center gap-2.5">
        <span className="font-mono text-[12px]" style={{ color: "var(--color-ink3)" }}>Try:</span>
        {tryChips.map((ex) => (
          <button
            key={ex.label}
            onClick={() => onSearch(ex.q)}
            className="font-mono text-[13px] px-4 py-2 rounded-full border transition hover:-translate-y-0.5"
            style={{ color: "var(--color-ink2)", background: "var(--color-panel)", borderColor: "var(--color-hairline2)" }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--color-accent)")}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--color-hairline2)")}
          >
            {ex.label}
          </button>
        ))}
      </div>

      {/* Highest-rated prompts — by AI quality, honestly labelled (no fabricated trends). */}
      {top.length > 0 && (
        <div className="max-w-[640px] mx-auto mt-14 text-left">
          <div className="flex items-baseline justify-between mb-3.5">
            <span className="font-display font-extrabold text-[17px] tracking-tight">Highest-rated prompts</span>
            <span className="font-mono text-[11px] uppercase tracking-wider" style={{ color: "var(--color-ink3)" }}>ranked by AI quality</span>
          </div>
          <div className="rounded-[15px] border overflow-hidden" style={{ background: "var(--color-panel)", borderColor: "var(--color-hairline)" }}>
            {top.slice(0, 5).map((it, i) => (
              <button
                key={it.id}
                onClick={() => onSearch(it.title)}
                className="w-full text-left grid items-center gap-3.5 px-4 py-3 border-t first:border-t-0 transition hover:bg-[var(--color-panel2)]"
                style={{ borderColor: "var(--color-hairline)", gridTemplateColumns: "26px 1fr auto" }}
              >
                <span className="font-mono text-[13px]" style={{ color: "var(--color-ink3)" }}>{i + 1}</span>
                <span>
                  <span className="block font-display font-bold text-[14.5px] tracking-tight">{it.title}</span>
                  <span className="block font-mono text-[10.5px] mt-0.5" style={{ color: "var(--color-ink3)" }}>{it.purpose}</span>
                </span>
                <span className="text-right min-w-[64px]">
                  <span className="block font-display font-extrabold text-[15px] leading-none tnum">{it.reliability}</span>
                  <span className="block font-mono text-[9px] uppercase tracking-wider mt-0.5" style={{ color: "var(--color-ink3)" }}>
                    {it.source === "votes" ? `${it.votes} votes` : "AI estimate"}
                  </span>
                </span>
              </button>
            ))}
          </div>
          <p className="font-mono text-[10.5px] mt-2" style={{ color: "var(--color-ink3)" }}>
            Scores are AI quality estimates. Real “worked / didn’t work” votes refine each prompt’s confidence over time.
          </p>
        </div>
      )}

      {/* Browse by category — real crawlable links to the server-rendered category pages. */}
      <nav aria-label="Browse prompt categories" className="max-w-[640px] mx-auto mt-12 text-left">
        <div className="font-mono text-[11px] uppercase tracking-wider mb-3" style={{ color: "var(--color-ink3)" }}>Browse by category</div>
        <div className="flex flex-wrap gap-2.5">
          {CATEGORIES.map((c) => (
            <a key={c.slug} href={`/category/${c.slug}`}
              className="font-mono text-[13px] px-4 py-2 rounded-full border transition hover:-translate-y-0.5"
              style={{ color: "var(--color-ink2)", background: "var(--color-panel)", borderColor: "var(--color-hairline2)" }}>
              {c.name}
            </a>
          ))}
        </div>
      </nav>

      {/* Visible FAQ — matches the FAQPage structured data so it reflects real on-page content. */}
      <section aria-label="Frequently asked questions" className="max-w-[640px] mx-auto mt-12 text-left">
        <h2 className="font-display font-extrabold text-[17px] tracking-tight mb-3.5">Frequently asked questions</h2>
        <div className="flex flex-col gap-2.5">
          {FAQ.map((f) => (
            <details key={f.q} className="rounded-[13px] border px-4 py-3" style={{ background: "var(--color-panel)", borderColor: "var(--color-hairline)" }}>
              <summary className="font-display font-bold text-[14.5px] cursor-pointer" style={{ color: "var(--color-ink)" }}>{f.q}</summary>
              <p className="text-[13.5px] mt-2" style={{ color: "var(--color-ink2)" }}>{f.a}</p>
            </details>
          ))}
        </div>
      </section>

      <Stats />
    </section>
  );
}

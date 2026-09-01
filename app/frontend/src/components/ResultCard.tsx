import { useState, type ReactNode } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { PromptResult } from "../types";
import { sourceLabel } from "../source";
import { MiniScore, band } from "./Scores";
import { ArtTile } from "./ArtTile";

const MEDAL = ["", "var(--color-gold)", "var(--color-silver)", "var(--color-bronze)"];

function highlightTemplate(t: string) {
  // wrap {VAR} tokens in an accent chip
  const parts = t.split(/(\{[^}]+\})/g);
  return parts.map((p, i) =>
    /^\{[^}]+\}$/.test(p) ? (
      <span key={i} className="font-mono px-1 rounded" style={{ background: "var(--color-accentsoft)", color: "var(--color-accent2)" }}>{p}</span>
    ) : (
      <span key={i}>{p}</span>
    )
  );
}

export function ResultCard({ r, rank, open, onToggle, onCopy, onPick, onRequireAuth }: {
  r: PromptResult; rank: number; open: boolean; onToggle: () => void;
  onCopy: (m: string) => void; onPick: (q: string) => void; onRequireAuth?: () => void;
}) {
  const s = r.scores;
  const isImg = r.prompt_type === "image";
  const { user, isSaved, toggleSave } = useAuth();
  const saved = isSaved(r.id);
  const onSave = async () => {
    if (!user) { onRequireAuth?.(); return; }
    try { await toggleSave(r.id); onCopy(saved ? "Removed from library" : "Saved to your library"); }
    catch { onCopy("Couldn't update library"); }
  };

  // live reliability (updates when the user votes)
  const [rel, setRel] = useState(r.reliability);
  const [voteMsg, setVoteMsg] = useState("");
  const relScore = rel.score;
  const liveOverall = Math.round(s.quality * 0.35 + s.match * 0.4 + relScore * 0.2 + 100 * 0.05);
  const castVote = async (verdict: "worked" | "didnt") => {
    try {
      const res = await api.vote(r.id, verdict, r.models[0]);
      setRel(res.reliability);
      setVoteMsg(verdict === "worked" ? "logged as worked" : "logged as didn't work");
    } catch {
      setVoteMsg("couldn't record vote");
    }
  };

  const overallBand = band(liveOverall);
  const overallCol = overallBand === "good" ? "var(--color-good)" : overallBand === "mid" ? "var(--color-mid)" : "var(--color-accent)";
  const overallSoft = overallBand === "good" ? "var(--color-goodsoft)" : overallBand === "mid" ? "var(--color-midsoft)" : "var(--color-accentsoft)";

  const copy = (text: string, msg: string) => {
    navigator.clipboard?.writeText(text).catch(() => {});
    onCopy(msg);
  };

  // live model-run preview (text/coding/data prompts)
  const [pv, setPv] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [pvOut, setPvOut] = useState("");
  const [pvModel, setPvModel] = useState("");
  const [pvErr, setPvErr] = useState("");
  const runPreview = async () => {
    setPv("loading"); setPvErr("");
    try {
      const res = await api.preview(r.id);
      setPvOut(res.output); setPvModel(res.model); setPv("done");
    } catch (e) {
      setPvErr(e instanceof Error && /503/.test(e.message) ? "Add an Anthropic API key (.env) to preview live output." : "Preview failed — try again.");
      setPv("error");
    }
  };

  return (
    <article
      className="rounded-2xl border mb-3 overflow-hidden transition-shadow"
      style={{
        background: "var(--color-panel)",
        borderColor: open || rank === 1 ? "var(--color-accentline)" : "var(--color-hairline)",
        boxShadow: open ? "0 0 0 1px var(--color-accentline), 0 24px 60px -30px rgba(20,24,31,.28)" : "0 8px 24px -14px rgba(20,24,31,.14)",
      }}
    >
      <button onClick={onToggle} aria-expanded={open}
        className="w-full text-left grid items-center gap-4 px-4.5 py-4"
        style={{ gridTemplateColumns: "46px 1fr auto" }}>
        <span className="w-[42px] h-[42px] rounded-[11px] flex items-center justify-center font-display font-black text-[19px] text-white"
          style={{ background: MEDAL[rank] ?? "var(--color-ink3)" }}>{rank}</span>
        <span>
          <span className="block font-display font-bold text-[17px] tracking-tight">{r.title}</span>
          <span className="block font-mono text-[11.5px] mt-0.5" style={{ color: "var(--color-ink3)" }}>
            {r.models.join(" · ")} · {rel.uses.toLocaleString()} uses
          </span>
        </span>
        <span className="flex gap-3.5 items-center">
          <MiniScore label="Quality" value={s.quality} />
          <MiniScore label="Match" value={s.match} suffix="%" />
          <MiniScore label="Reliab." value={relScore} />
          <span className="flex flex-col items-center justify-center w-[58px] h-[58px] rounded-[13px] shrink-0" style={{ background: overallSoft }}>
            <span className="font-display font-black text-[21px] leading-none tnum" style={{ color: overallCol }}>{liveOverall}</span>
            <span className="font-mono text-[8px] uppercase tracking-wider mt-0.5" style={{ color: overallCol }}>Overall</span>
          </span>
        </span>
      </button>

      <div style={{ maxHeight: open ? 2000 : 0, overflow: "hidden", transition: "max-height .4s cubic-bezier(.4,0,.1,1)" }}>
        <div className="px-4.5 pb-5 pt-1 border-t" style={{ borderColor: "var(--color-hairline)" }}>
          <div className="grid gap-5 mt-4 md:grid-cols-[1.1fr_0.9fr] grid-cols-1">
            {/* why + weakness */}
            <div>
              <div className="font-mono text-[10.5px] uppercase tracking-wider mb-2.5" style={{ color: "var(--color-ink3)" }}>Why we recommend this</div>
              <div className="flex flex-col gap-2">
                {r.why.map((w, i) => (
                  <div key={i} className="flex gap-2.5 text-[13.5px]" style={{ color: "var(--color-ink)" }}>
                    <span className="font-mono font-bold shrink-0" style={{ color: "var(--color-good)" }}>✓</span>{w}
                  </div>
                ))}
              </div>
              <div className="flex gap-2.5 items-start text-[13px] rounded-[10px] px-3.5 py-3 mt-3.5"
                style={{ color: "var(--color-ink)", background: "var(--color-midsoft)", border: "1px solid color-mix(in srgb, var(--color-mid) 32%, transparent)" }}>
                <span className="font-mono font-bold shrink-0" style={{ color: "var(--color-mid)" }}>!</span>
                <span><b>Weakness — </b>{r.weakness}</span>
              </div>
            </div>

            {/* prompt / sample + provenance */}
            <div>
              <div className="font-mono text-[10.5px] uppercase tracking-wider mb-2.5" style={{ color: "var(--color-ink3)" }}>
                {isImg ? "Sample output" : "The prompt"}
              </div>
              {isImg ? (
                <>
                  <div className="relative rounded-xl overflow-hidden border aspect-[4/5]" style={{ borderColor: "var(--color-hairline)" }}>
                    <ArtTile seed={rank} />
                    <span className="absolute left-2.5 bottom-2.5 z-[2] font-mono text-[9.5px] text-white px-2 py-0.5 rounded-full" style={{ background: "rgba(10,14,20,.55)" }}>
                      Representative sample · {r.models[0]}
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 mt-2.5">
                    {[7, 13, 23].map((o) => (
                      <div key={o} className="relative rounded-lg overflow-hidden border aspect-square" style={{ borderColor: "var(--color-hairline)" }}>
                        <ArtTile seed={rank + o} />
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <div className="rounded-xl border p-4 font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap max-h-[220px] overflow-y-auto"
                    style={{ background: "var(--color-panel2)", borderColor: "var(--color-hairline)", color: "var(--color-ink)" }}>
                    {r.prompt}
                  </div>

                  {pv === "idle" && (
                    <button onClick={runPreview}
                      className="mt-2.5 font-mono text-[12px] px-3.5 py-2 rounded-[10px] border inline-flex items-center gap-2 transition hover:-translate-y-0.5"
                      style={{ borderColor: "var(--color-accentline)", background: "var(--color-accentsoft)", color: "var(--color-accent2)" }}>
                      ▶ Preview live output
                    </button>
                  )}
                  {pv === "loading" && (
                    <div className="mt-2.5 font-mono text-[12px] flex items-center gap-2" style={{ color: "var(--color-accent2)" }}>
                      <span className="inline-block w-3 h-3 rounded-full border-2 animate-spin"
                        style={{ borderColor: "var(--color-accentline)", borderTopColor: "var(--color-accent)" }} />
                      Running the prompt on a live model…
                    </div>
                  )}
                  {pv === "error" && (
                    <div className="mt-2.5 font-mono text-[11.5px]" style={{ color: "var(--color-ink3)" }}>{pvErr}</div>
                  )}
                  {pv === "done" && (
                    <div className="mt-2.5 rounded-xl border p-4 text-[13px] leading-relaxed whitespace-pre-wrap"
                      style={{ background: "var(--color-sunk)", borderColor: "var(--color-hairline)", color: "var(--color-ink2)" }}>
                      <div className="font-mono text-[10px] uppercase tracking-wide mb-2 flex items-center justify-between" style={{ color: "var(--color-accent2)" }}>
                        <span>Live output · {pvModel}</span>
                        <button onClick={runPreview} className="normal-case" style={{ color: "var(--color-ink3)" }}>↻ regenerate</button>
                      </div>
                      {pvOut}
                    </div>
                  )}
                </>
              )}

              <div className="grid grid-cols-3 max-[560px]:grid-cols-2 gap-px rounded-xl overflow-hidden border mt-3.5" style={{ background: "var(--color-hairline)", borderColor: "var(--color-hairline)" }}>
                {(() => {
                  const src = sourceLabel(r.provenance.source, r.provenance.url);
                  const sourceCell: ReactNode = src.url ? (
                    <a href={src.url} target="_blank" rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="inline-flex items-center gap-1 hover:underline"
                      style={{ color: "var(--color-accent2)" }}>
                      {src.label} <span aria-hidden className="text-[10px]">↗</span>
                    </a>
                  ) : src.label;
                  const rows: [string, ReactNode][] = [
                    ["Source", sourceCell],
                    ["Tested", rel.tested.join(", ")],
                    ["Useful", `${rel.useful}%`],
                    ["Verified", rel.last_verified],
                    ["Version", r.provenance.version],
                    ["Eval", r.provenance.eval_source],
                  ];
                  return rows.map(([k, v]) => (
                    <div key={k} className="p-2.5" style={{ background: "var(--color-panel)" }}>
                      <div className="font-mono text-[9.5px] uppercase tracking-wide" style={{ color: "var(--color-ink3)" }}>{k}</div>
                      <div className="text-[12.5px] font-medium mt-0.5" style={{ color: "var(--color-ink)" }}>{v}</div>
                    </div>
                  ));
                })()}
              </div>
            </div>
          </div>

          {/* template */}
          {r.is_template && r.variables.length > 0 && (
            <div className="mt-5 border-t pt-4" style={{ borderColor: "var(--color-hairline)" }}>
              <div className="font-mono text-[10.5px] uppercase tracking-wider mb-2.5" style={{ color: "var(--color-ink3)" }}>Reusable template</div>
              <div className="rounded-xl border p-4 font-mono text-[12.5px] leading-relaxed" style={{ background: "var(--color-panel2)", borderColor: "var(--color-hairline)" }}>
                {highlightTemplate(r.template)}
              </div>
              <div className="flex flex-wrap gap-2 mt-2.5">
                {r.variables.map((v) => (
                  <span key={v} className="font-mono text-[11px] px-2 py-1 rounded-md border" style={{ background: "var(--color-accentsoft)", borderColor: "var(--color-accentline)", color: "var(--color-accent2)" }}>{"{" + v + "}"}</span>
                ))}
              </div>
            </div>
          )}

          {/* same job, other tools */}
          <div className="mt-5 border-t pt-4" style={{ borderColor: "var(--color-hairline)" }}>
            <div className="font-mono text-[10.5px] uppercase tracking-wider mb-3" style={{ color: "var(--color-ink3)" }}>Same job, other tools</div>
            <div className="grid grid-cols-4 max-[720px]:grid-cols-2 gap-2.5">
              {[
                { n: "AIPRM", p: "Community prompt, no fit score.", tag: "free · untested", us: false },
                { n: "PromptBase", p: "Buy ($2.99) before you see output.", tag: "paid · unproven", us: false },
                { n: "FlowGPT", p: "Ranked by popularity, not fit.", tag: "free · social", us: false },
                { n: "Prompt Finder", p: `${s.overall} overall · tested on ${r.models[0]} · why + sample.`, tag: "free · verified", us: true },
              ].map((c) => (
                <div key={c.n} className="rounded-[11px] border p-3.5"
                  style={{ background: c.us ? "var(--color-accentsoft)" : "var(--color-panel2)", borderColor: c.us ? "var(--color-accent)" : "var(--color-hairline)" }}>
                  <div className="font-display font-bold text-[13px]" style={{ color: c.us ? "var(--color-accent2)" : "var(--color-ink)" }}>{c.n}</div>
                  <div className="font-mono text-[11px] mt-2 leading-relaxed" style={{ color: "var(--color-ink2)" }}>{c.p}</div>
                  <span className="inline-block mt-2.5 font-mono text-[9.5px] px-2 py-0.5 rounded-full"
                    style={{ background: c.us ? "var(--color-accent)" : "var(--color-sunk)", color: c.us ? "#fff" : "var(--color-ink3)" }}>{c.tag}</span>
                </div>
              ))}
            </div>
          </div>

          {/* actions */}
          <div className="flex gap-2.5 flex-wrap mt-5">
            <button onClick={() => copy(r.prompt, "Prompt copied — paste into your model")}
              className="font-display font-bold text-[14.5px] px-5 py-3 rounded-[11px] text-white active:scale-[0.98] transition"
              style={{ background: "var(--color-accent)" }}>Use this prompt</button>
            {r.is_template && (
              <button onClick={() => copy(r.template, "Template copied")}
                className="font-mono text-[13px] px-4.5 py-3 rounded-[11px] border"
                style={{ borderColor: "var(--color-hairline2)", background: "var(--color-panel)", color: "var(--color-ink)" }}>Copy template</button>
            )}
            <button onClick={onSave}
              className="font-mono text-[13px] px-4.5 py-3 rounded-[11px] border transition"
              style={saved
                ? { borderColor: "var(--color-accent)", background: "var(--color-accentsoft)", color: "var(--color-accent2)" }
                : { borderColor: "var(--color-hairline2)", background: "var(--color-panel)", color: "var(--color-ink)" }}>
              {saved ? "★ Saved" : "☆ Save"}
            </button>
            <button onClick={() => onPick(r.purpose + " prompts")}
              className="font-mono text-[13px] px-4.5 py-3 rounded-[11px] border"
              style={{ borderColor: "var(--color-hairline2)", background: "var(--color-panel)", color: "var(--color-ink)" }}>More like this</button>
          </div>

          {/* outcome vote — the Reliability flywheel */}
          <div className="mt-4 border-t pt-4 flex items-center gap-3 flex-wrap" style={{ borderColor: "var(--color-hairline)" }}>
            <span className="font-mono text-[11.5px]" style={{ color: "var(--color-ink3)" }}>Did it work?</span>
            <button onClick={() => castVote("worked")}
              className="font-mono text-[12px] px-3 py-1.5 rounded-lg border transition hover:-translate-y-0.5"
              style={{ borderColor: "color-mix(in srgb, var(--color-good) 40%, transparent)", background: "var(--color-goodsoft)", color: "var(--color-good)" }}>👍 Worked</button>
            <button onClick={() => castVote("didnt")}
              className="font-mono text-[12px] px-3 py-1.5 rounded-lg border transition hover:-translate-y-0.5"
              style={{ borderColor: "color-mix(in srgb, var(--color-weak) 40%, transparent)", background: "var(--color-weaksoft)", color: "var(--color-weak)" }}>👎 Didn't work</button>
            <span className="font-mono text-[11px]" style={{ color: "var(--color-ink3)" }}>
              {rel.source === "votes"
                ? `Reliability ${rel.score} · verified by ${rel.votes} vote${rel.votes === 1 ? "" : "s"} (${rel.useful}% useful)`
                : `Reliability ${rel.score} · seeded estimate`}
              {voteMsg && ` — ${voteMsg}`}
            </span>
          </div>
        </div>
      </div>
    </article>
  );
}

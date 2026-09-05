import { useEffect, useState } from "react";
import { api, type ActivityResult } from "../api";

function ago(iso: string | null | undefined): { text: string; stale: boolean } {
  if (!iso) return { text: "never", stale: true };
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  const stale = secs > 6 * 3600; // refresh runs every 3h — >6h means something's wrong
  if (secs < 90) return { text: "just now", stale };
  if (secs < 3600) return { text: `${Math.round(secs / 60)} min ago`, stale };
  if (secs < 172800) return { text: `${Math.round(secs / 3600)} h ago`, stale };
  return { text: `${Math.round(secs / 86400)} days ago`, stale };
}

export function AdminActivity({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<ActivityResult | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.activity().then(setData).catch((e) => setErr(e instanceof Error ? e.message : "Failed to load"));
  }, []);

  const refreshed = ago(data?.last_refreshed);
  const label = "font-mono text-[10px] uppercase tracking-wide";
  const status = data?.days[0]?.grading_status;
  const awaiting = data?.days[0]?.awaiting ?? 0;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      style={{ background: "color-mix(in srgb, var(--color-ink) 45%, transparent)" }} onClick={onClose}>
      <div className="w-full max-w-[560px] rounded-2xl border p-6 max-h-[85vh] overflow-y-auto"
        style={{ background: "var(--color-panel)", borderColor: "var(--color-hairline2)", boxShadow: "0 30px 70px -30px rgba(0,0,0,.5)" }}
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-baseline justify-between mb-1">
          <div className="font-display font-extrabold text-[17px] tracking-tight">Daily activity</div>
          <span className="font-mono text-[11px]" style={{ color: refreshed.stale ? "var(--color-weak)" : "var(--color-ink3)" }}>
            last refresh {refreshed.text}
          </span>
        </div>
        <p className="text-[12.5px] mb-4" style={{ color: "var(--color-ink2)" }}>
          Prompts pulled and AI-graded each day by the automatic refresh.
        </p>

        {status === "out_of_credits" && (
          <div className="mb-4 rounded-[10px] px-3.5 py-3 text-[13px] leading-relaxed"
            style={{ background: "var(--color-weaksoft)", border: "1px solid color-mix(in srgb, var(--color-weak) 45%, transparent)", color: "var(--color-ink)" }}>
            <b style={{ color: "var(--color-weak)" }}>⏸ Grading paused — out of Anthropic credits.</b><br />
            New prompts are still being collected ({awaiting} awaiting grades). Add credits at{" "}
            <a href="https://console.anthropic.com/settings/billing" target="_blank" rel="noopener noreferrer"
              style={{ color: "var(--color-accent2)", textDecoration: "underline" }}>console.anthropic.com</a>{" "}
            and grading resumes automatically.
          </div>
        )}
        {status === "error" && (
          <div className="mb-4 rounded-[10px] px-3.5 py-2.5 text-[12.5px]"
            style={{ background: "var(--color-weaksoft)", border: "1px solid color-mix(in srgb, var(--color-weak) 35%, transparent)", color: "var(--color-ink)" }}>
            ⚠ Grading hit an API error on the last run — prompts are queued and will grade on the next run.
          </div>
        )}
        {refreshed.stale && data && status !== "out_of_credits" && (
          <div className="mb-4 rounded-[10px] px-3.5 py-2.5 text-[12.5px]"
            style={{ background: "var(--color-weaksoft)", border: "1px solid color-mix(in srgb, var(--color-weak) 35%, transparent)", color: "var(--color-ink)" }}>
            ⚠ The refresh hasn't run in over 6 hours — the scheduled job may be stalled on the server.
          </div>
        )}

        {err && <div className="font-mono text-[12px]" style={{ color: "var(--color-weak)" }}>{err}</div>}
        {!data && !err && <div className="font-mono text-[12px]" style={{ color: "var(--color-ink3)" }}>Loading…</div>}

        {data && data.days.length === 0 && (
          <div className="text-[13px]" style={{ color: "var(--color-ink3)" }}>
            No refreshes logged yet — the first entry appears after the next run.
          </div>
        )}

        {data && data.days.length > 0 && (
          <div className="rounded-xl border overflow-hidden" style={{ borderColor: "var(--color-hairline)" }}>
            <div className="grid px-3.5 py-2 border-b" style={{ gridTemplateColumns: "1.2fr 1fr 1fr 1fr", background: "var(--color-panel2)", borderColor: "var(--color-hairline)" }}>
              {["Date", "Pulled", "AI-graded", "Total"].map((h) => (
                <span key={h} className={label} style={{ color: "var(--color-ink3)" }}>{h}</span>
              ))}
            </div>
            {data.days.map((d) => (
              <div key={d.date} className="grid px-3.5 py-2.5 border-b last:border-b-0 items-center"
                style={{ gridTemplateColumns: "1.2fr 1fr 1fr 1fr", borderColor: "var(--color-hairline)" }}>
                <span className="text-[12.5px] font-medium" style={{ color: "var(--color-ink)" }}>{d.date}</span>
                <span className="font-display font-bold text-[14px] tnum" style={{ color: "var(--color-accent2)" }}>+{d.pulled}</span>
                <span className="font-display font-bold text-[14px] tnum" style={{ color: "var(--color-good)" }}>{d.graded}</span>
                <span className="text-[12.5px] tnum" style={{ color: "var(--color-ink2)" }}>
                  {d.total.toLocaleString()}
                  <span className="font-mono text-[10px] ml-1" style={{ color: "var(--color-ink3)" }}>({d.awaiting} left)</span>
                </span>
              </div>
            ))}
          </div>
        )}

        <div className="mt-4 flex justify-end">
          <button onClick={onClose} className="font-display font-bold text-[14px] px-5 py-2 rounded-[11px] text-white active:scale-[0.98]"
            style={{ background: "var(--color-accent)" }}>Done</button>
        </div>
      </div>
    </div>
  );
}

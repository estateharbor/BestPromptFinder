import { useMemo, useState } from "react";
import { api } from "../api";

// Fill a template's {placeholders} from the user's values. Unfilled ones become clearly
// bracketed [placeholders] so a copied/previewed prompt never carries invented specifics.
function compile(template: string, values: Record<string, string>): string {
  return template.replace(/\{([^}]+)\}/g, (_, raw) => {
    const v = (values[raw.trim()] || "").trim();
    return v || `[${raw.trim()}]`;
  });
}

// Render the compiled prompt with unfilled [brackets] highlighted so gaps are obvious.
function highlight(text: string) {
  return text.split(/(\[[^\]]+\])/g).map((p, i) =>
    /^\[[^\]]+\]$/.test(p)
      ? <span key={i} className="font-mono px-1 rounded" style={{ background: "var(--color-midsoft)", color: "var(--color-mid)" }}>{p}</span>
      : <span key={i}>{p}</span>
  );
}

// Turn a variable name into a readable label: quarterly_results -> "Quarterly results".
function labelize(v: string): string {
  const s = v.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function VariableForm({ id, template, variables, goal, onCopy }: {
  id: string; template: string; variables: string[]; goal: string; onCopy: (m: string) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(
    () => Object.fromEntries(variables.map((v) => [v, ""]))
  );
  const [prefilling, setPrefilling] = useState(false);
  const [pv, setPv] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [pvOut, setPvOut] = useState("");
  const [pvModel, setPvModel] = useState("");
  const [pvErr, setPvErr] = useState("");

  const missing = variables.filter((v) => !(values[v] || "").trim());
  const compiled = useMemo(() => compile(template, values), [template, values]);

  const set = (k: string, v: string) => setValues((prev) => ({ ...prev, [k]: v }));

  const prefill = async () => {
    setPrefilling(true);
    try {
      const res = await api.fill(id, goal);
      setValues((prev) => ({ ...prev, ...res.values }));
      const got = Object.values(res.values).filter((v) => v && v.trim()).length;
      onCopy(got ? `Prefilled ${got} field${got === 1 ? "" : "s"} from your goal` : "Nothing to prefill — add your details below");
    } catch {
      onCopy("Couldn't auto-fill — fill the fields manually");
    } finally {
      setPrefilling(false);
    }
  };

  const copyFilled = () => {
    navigator.clipboard?.writeText(compiled).catch(() => {});
    onCopy(missing.length
      ? `Copied — fill ${missing.length} bracketed field${missing.length === 1 ? "" : "s"} before running`
      : "Filled prompt copied — paste into your model");
  };

  const runPreview = async () => {
    if (missing.length) return;
    setPv("loading"); setPvErr("");
    try {
      const res = await api.preview(id, compiled);
      setPvOut(res.output); setPvModel(res.model); setPv("done");
    } catch (e) {
      setPvErr(e instanceof Error && /503/.test(e.message)
        ? "Add an Anthropic API key (.env) to preview live output."
        : "Preview failed — try again.");
      setPv("error");
    }
  };

  return (
    <div className="mt-5 border-t pt-4" style={{ borderColor: "var(--color-hairline)" }}>
      <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <span className="font-mono text-[10.5px] uppercase tracking-wider" style={{ color: "var(--color-ink3)" }}>
          Fill in & use this template
        </span>
        {goal.trim() && (
          <button onClick={prefill} disabled={prefilling}
            className="font-mono text-[11.5px] px-3 py-1.5 rounded-lg border inline-flex items-center gap-1.5 transition hover:-translate-y-0.5 disabled:opacity-60"
            style={{ borderColor: "var(--color-accentline)", background: "var(--color-accentsoft)", color: "var(--color-accent2)" }}>
            {prefilling ? "Prefilling…" : "✨ Prefill from my goal"}
          </button>
        )}
      </div>

      {/* one input per variable */}
      <div className="grid gap-3 sm:grid-cols-2 grid-cols-1">
        {variables.map((v) => {
          const empty = !(values[v] || "").trim();
          return (
            <label key={v} className="flex flex-col gap-1">
              <span className="font-mono text-[11px]" style={{ color: "var(--color-ink2)" }}>
                {labelize(v)} {empty && <span style={{ color: "var(--color-mid)" }}>· required</span>}
              </span>
              <input
                value={values[v] || ""}
                onChange={(e) => set(v, e.target.value)}
                placeholder={`Enter ${labelize(v).toLowerCase()}…`}
                className="rounded-[10px] border px-3 py-2 text-[13.5px] outline-none"
                style={{
                  background: "var(--color-panel2)",
                  borderColor: empty ? "color-mix(in srgb, var(--color-mid) 40%, transparent)" : "var(--color-hairline2)",
                  color: "var(--color-ink)",
                }}
              />
            </label>
          );
        })}
      </div>

      {/* live compiled prompt */}
      <div className="font-mono text-[10.5px] uppercase tracking-wider mt-4 mb-2" style={{ color: "var(--color-ink3)" }}>
        Your completed prompt
      </div>
      <div className="rounded-xl border p-4 font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap max-h-[220px] overflow-y-auto"
        style={{ background: "var(--color-panel2)", borderColor: "var(--color-hairline)", color: "var(--color-ink)" }}>
        {highlight(compiled)}
      </div>
      {missing.length > 0 && (
        <div className="font-mono text-[11px] mt-2" style={{ color: "var(--color-mid)" }}>
          Still needs: {missing.map(labelize).join(", ")} — highlighted above. Preview stays fabrication-free until these are filled.
        </div>
      )}

      {/* actions */}
      <div className="flex gap-2.5 flex-wrap mt-3">
        <button onClick={copyFilled}
          className="font-display font-bold text-[14px] px-5 py-2.5 rounded-[11px] text-white active:scale-[0.98] transition"
          style={{ background: "var(--color-accent)" }}>Use filled prompt</button>
        <button onClick={runPreview} disabled={missing.length > 0 || pv === "loading"}
          title={missing.length ? "Fill the required fields to preview" : undefined}
          className="font-mono text-[13px] px-4 py-2.5 rounded-[11px] border inline-flex items-center gap-2 transition disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ borderColor: "var(--color-accentline)", background: "var(--color-accentsoft)", color: "var(--color-accent2)" }}>
          {pv === "loading" ? "Running…" : "▶ Preview filled output"}
        </button>
      </div>

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
    </div>
  );
}

import { useRef, useState } from "react";
import { api, type IngestResult } from "../api";

const ACCEPT = ".xlsx,.xls,.csv";

export function UploadModal({ onClose, onDone }: { onClose: () => void; onDone: (msg: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<IngestResult | null>(null);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const pick = (f: File | null | undefined) => {
    if (!f) return;
    const ok = /\.(xlsx|xls|csv)$/i.test(f.name);
    setErr(ok ? "" : "Please choose an .xlsx, .xls, or .csv file.");
    setFile(ok ? f : null);
    setResult(null);
  };

  const upload = async () => {
    if (!file) return;
    setBusy(true); setErr("");
    try {
      setResult(await api.ingest(file));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const finish = () => {
    if (result) onDone(`${result.added} prompts added to the library`);
    onClose();
  };

  const label = "font-mono text-[10.5px] uppercase tracking-wide";
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      style={{ background: "color-mix(in srgb, var(--color-ink) 45%, transparent)" }} onClick={onClose}>
      <div className="w-full max-w-[460px] rounded-2xl border p-6"
        style={{ background: "var(--color-panel)", borderColor: "var(--color-hairline2)", boxShadow: "var(--shadow-lg, 0 30px 70px -30px rgba(0,0,0,.5))" }}
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2.5 font-display font-extrabold text-[17px] tracking-tight mb-1">
          <span className="w-[11px] h-[11px] rounded-full" style={{ background: "var(--color-accent)", boxShadow: "0 0 0 3px var(--color-accentsoft)" }} />
          Upload prompts
        </div>
        <p className="text-[13.5px] mb-4" style={{ color: "var(--color-ink2)" }}>
          Add an Excel or CSV of prompts. They're cleaned, deduped, graded, and added to the library.
        </p>

        {!result ? (
          <>
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}
              className="w-full rounded-[12px] border-2 border-dashed px-4 py-8 text-center transition"
              style={{
                borderColor: drag ? "var(--color-accent)" : "var(--color-hairline2)",
                background: drag ? "var(--color-accentsoft)" : "var(--color-panel2)",
              }}
            >
              <div className="text-[13.5px]" style={{ color: "var(--color-ink)" }}>
                {file ? file.name : "Drag a file here, or click to choose"}
              </div>
              <div className="mt-1 font-mono text-[11px]" style={{ color: "var(--color-ink3)" }}>
                {file ? `${(file.size / 1024).toFixed(0)} KB` : ".xlsx · .csv · columns: title, prompt (rest optional)"}
              </div>
            </button>
            <input ref={inputRef} type="file" accept={ACCEPT} className="hidden"
              onChange={(e) => pick(e.target.files?.[0])} />

            {err && <div className="mt-3 font-mono text-[11.5px]" style={{ color: "var(--color-weak)" }}>{err}</div>}

            <div className="mt-4 flex items-center justify-end gap-2">
              <button onClick={onClose} className="font-mono text-[12px] px-3.5 py-2 rounded-[10px] border"
                style={{ color: "var(--color-ink2)", borderColor: "var(--color-hairline2)", background: "var(--color-panel)" }}>
                Cancel
              </button>
              <button onClick={upload} disabled={!file || busy}
                className="font-display font-bold text-[14px] px-5 py-2 rounded-[11px] text-white disabled:opacity-50 active:scale-[0.98] transition"
                style={{ background: "var(--color-accent)" }}>
                {busy ? "Uploading…" : "Upload & grade"}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="rounded-[12px] border p-4" style={{ borderColor: "var(--color-hairline)", background: "var(--color-panel2)" }}>
              <div className="grid grid-cols-3 gap-3 text-center">
                {[["added", result.added, "var(--color-good)"], ["queued", result.queued_for_grading, "var(--color-accent2)"], ["skipped", result.skipped, "var(--color-ink3)"]].map(
                  ([lab, n, col]) => (
                    <div key={lab as string}>
                      <div className="font-display font-black text-[22px] leading-none tnum" style={{ color: col as string }}>{n as number}</div>
                      <div className={label} style={{ color: "var(--color-ink3)", marginTop: 4 }}>{lab as string}</div>
                    </div>
                  )
                )}
              </div>
              <p className="text-[12.5px] mt-3 pt-3 border-t" style={{ color: "var(--color-ink2)", borderColor: "var(--color-hairline)" }}>
                {result.message}
              </p>
            </div>

            {result.added_titles.length > 0 && (
              <div className="mt-3 max-h-[150px] overflow-y-auto">
                <div className={label} style={{ color: "var(--color-ink3)", marginBottom: 6 }}>Added</div>
                <ul className="flex flex-col gap-1">
                  {result.added_titles.map((t) => (
                    <li key={t} className="text-[12.5px] truncate" style={{ color: "var(--color-ink2)" }}>· {t}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-4 flex items-center justify-end gap-2">
              <button onClick={() => { setFile(null); setResult(null); }}
                className="font-mono text-[12px] px-3.5 py-2 rounded-[10px] border"
                style={{ color: "var(--color-ink2)", borderColor: "var(--color-hairline2)", background: "var(--color-panel)" }}>
                Upload another
              </button>
              <button onClick={finish}
                className="font-display font-bold text-[14px] px-5 py-2 rounded-[11px] text-white active:scale-[0.98] transition"
                style={{ background: "var(--color-accent)" }}>
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

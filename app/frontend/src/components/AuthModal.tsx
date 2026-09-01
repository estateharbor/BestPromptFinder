import { useState } from "react";
import { useAuth } from "../auth";

export function AuthModal({ onClose }: { onClose: () => void }) {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      await (mode === "login" ? login(email, password) : register(email, password));
      onClose();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      style={{ background: "color-mix(in srgb, var(--color-ink) 45%, transparent)" }} onClick={onClose}>
      <div className="w-full max-w-[400px] rounded-2xl border p-6"
        style={{ background: "var(--color-panel)", borderColor: "var(--color-hairline2)", boxShadow: "var(--shadow-lg, 0 30px 70px -30px rgba(0,0,0,.5))" }}
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2.5 font-display font-extrabold text-[17px] tracking-tight mb-1">
          <span className="w-[11px] h-[11px] rounded-full" style={{ background: "var(--color-accent)", boxShadow: "0 0 0 3px var(--color-accentsoft)" }} />
          {mode === "login" ? "Welcome back" : "Create your account"}
        </div>
        <p className="text-[13.5px] mb-4" style={{ color: "var(--color-ink2)" }}>
          {mode === "login" ? "Sign in to your prompt library." : "Save prompts to a private library that follows you."}
        </p>

        <form onSubmit={submit} className="flex flex-col gap-2.5">
          <input type="email" required placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)}
            className="rounded-[10px] border px-3.5 py-2.5 text-[14px] outline-none"
            style={{ background: "var(--color-panel2)", borderColor: "var(--color-hairline2)", color: "var(--color-ink)" }} />
          <input type="password" required placeholder={mode === "register" ? "At least 8 characters" : "Password"} value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded-[10px] border px-3.5 py-2.5 text-[14px] outline-none"
            style={{ background: "var(--color-panel2)", borderColor: "var(--color-hairline2)", color: "var(--color-ink)" }} />
          {err && <div className="font-mono text-[11.5px]" style={{ color: "var(--color-weak)" }}>{err}</div>}
          <button type="submit" disabled={busy}
            className="mt-1 font-display font-bold text-[14.5px] px-5 py-2.5 rounded-[11px] text-white disabled:opacity-60 active:scale-[0.98] transition"
            style={{ background: "var(--color-accent)" }}>
            {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <button onClick={() => { setMode(mode === "login" ? "register" : "login"); setErr(""); }}
          className="mt-3 font-mono text-[12px]" style={{ color: "var(--color-accent2)" }}>
          {mode === "login" ? "New here? Create an account" : "Already have an account? Sign in"}
        </button>
      </div>
    </div>
  );
}

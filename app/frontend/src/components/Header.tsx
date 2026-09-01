import { useAuth } from "../auth";

export function Header({ showNew, onNew, onHome, onLibrary, onAuth, onUpload }: {
  showNew: boolean;
  onNew: () => void;
  onHome: () => void;
  onLibrary: () => void;
  onAuth: () => void;
  onUpload: () => void;
}) {
  const { user, logout } = useAuth();
  const pill = "font-mono text-[11.5px] px-3 py-1.5 rounded-lg border";
  const pillStyle = { color: "var(--color-ink2)", borderColor: "var(--color-hairline2)", background: "var(--color-panel)" } as const;

  return (
    <header className="sticky top-0 z-40 border-b"
      style={{ background: "color-mix(in srgb, var(--color-ground) 90%, transparent)", backdropFilter: "blur(10px)", borderColor: "var(--color-hairline)" }}>
      <div className="max-w-[920px] mx-auto px-6 h-[58px] flex items-center gap-3">
        <button onClick={onHome} className="flex items-center gap-2.5 font-display font-extrabold text-[16px] tracking-tight">
          <span className="w-[11px] h-[11px] rounded-full" style={{ background: "var(--color-accent)", boxShadow: "0 0 0 3px var(--color-accentsoft)" }} />
          Prompt&nbsp;Finder
        </button>

        <div className="ml-auto flex items-center gap-2">
          {showNew && <button onClick={onNew} className={pill} style={pillStyle}>↩ New search</button>}
          {user ? (
            <>
              {user.is_admin && (
                <button onClick={onUpload} className={pill} style={pillStyle} title="Upload prompts (admin)">
                  ⬆ Upload
                </button>
              )}
              <button onClick={onLibrary} className={pill} style={{ ...pillStyle, color: "var(--color-accent2)", borderColor: "var(--color-accentline)", background: "var(--color-accentsoft)" }}>
                ★ My library
              </button>
              <span className="font-mono text-[11.5px] hidden sm:inline" style={{ color: "var(--color-ink3)" }}>{user.email}</span>
              <button onClick={logout} className={pill} style={pillStyle}>Sign out</button>
            </>
          ) : (
            <button onClick={onAuth} className="font-mono text-[11.5px] px-3.5 py-1.5 rounded-lg text-white" style={{ background: "var(--color-accent)" }}>
              Sign in
            </button>
          )}
        </div>
      </div>
    </header>
  );
}

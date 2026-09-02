import { useEffect, useState } from "react";

// The Chrome/Android "install" event (not in the standard lib types).
type BIPEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };

export function InstallButton() {
  const [deferred, setDeferred] = useState<BIPEvent | null>(null);
  const [iosOpen, setIosOpen] = useState(false);
  const [hidden, setHidden] = useState(false);

  const ua = typeof navigator !== "undefined" ? navigator.userAgent : "";
  const isIOS = /iphone|ipad|ipod/i.test(ua);
  // iOS Safari (not Chrome/Firefox/Edge on iOS, which can't install)
  const isIOSSafari = isIOS && /safari/i.test(ua) && !/crios|fxios|edgios/i.test(ua);
  const standalone =
    typeof window !== "undefined" &&
    (window.matchMedia?.("(display-mode: standalone)").matches ||
      (navigator as unknown as { standalone?: boolean }).standalone === true);

  useEffect(() => {
    if (standalone) { setHidden(true); return; }
    const onBIP = (e: Event) => { e.preventDefault(); setDeferred(e as BIPEvent); };
    const onInstalled = () => { setHidden(true); setDeferred(null); };
    window.addEventListener("beforeinstallprompt", onBIP);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onBIP);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, [standalone]);

  const showAndroid = !!deferred;         // Chrome/Edge fired the install event
  const showIOS = isIOSSafari && !standalone;
  if (hidden || (!showAndroid && !showIOS)) return null;

  const click = async () => {
    if (deferred) {
      await deferred.prompt();
      try { await deferred.userChoice; } catch { /* dismissed */ }
      setDeferred(null);
    } else {
      setIosOpen((v) => !v);
    }
  };

  return (
    <div className="relative">
      <button
        onClick={click}
        title="Install BestPromptFinder"
        className="font-mono text-[11.5px] px-3 py-1.5 rounded-lg border transition hover:-translate-y-0.5"
        style={{ color: "var(--color-accent2)", borderColor: "var(--color-accentline)", background: "var(--color-accentsoft)" }}
      >
        ⬇ Install
      </button>

      {iosOpen && (
        <>
          {/* click-away backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setIosOpen(false)} />
          <div
            className="absolute right-0 mt-2 w-[248px] rounded-xl border p-4 z-50 text-left"
            style={{ background: "var(--color-panel)", borderColor: "var(--color-hairline2)", boxShadow: "0 20px 50px -20px rgba(0,0,0,.55)" }}
          >
            <div className="font-display font-bold text-[14px] mb-1.5">Install on iPhone</div>
            <ol className="text-[12.5px] leading-relaxed list-decimal pl-4" style={{ color: "var(--color-ink2)" }}>
              <li>Tap the <b>Share</b> button in Safari's toolbar</li>
              <li>Scroll and choose <b>“Add to Home Screen”</b></li>
              <li>Tap <b>Add</b></li>
            </ol>
            <button onClick={() => setIosOpen(false)} className="mt-3 font-mono text-[11.5px]" style={{ color: "var(--color-accent2)" }}>
              Got it
            </button>
          </div>
        </>
      )}
    </div>
  );
}

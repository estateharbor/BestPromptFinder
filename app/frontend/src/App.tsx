import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { SearchResponse } from "./types";
import { AuthProvider } from "./auth";
import { Header } from "./components/Header";
import { Home } from "./components/Home";
import { Loading } from "./components/Loading";
import { Results } from "./components/Results";
import { Library } from "./components/Library";
import { AuthModal } from "./components/AuthModal";
import { UploadModal } from "./components/UploadModal";
import { AdminActivity } from "./components/AdminActivity";
import { Footer } from "./components/Footer";
import { Toast } from "./components/Toast";

type View = "home" | "loading" | "results" | "library";

function Shell() {
  const [view, setView] = useState<View>("home");
  const [data, setData] = useState<SearchResponse | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const [refining, setRefining] = useState(false);
  const latest = useRef(0);  // id of the newest search, so a slow AI reply can't overwrite a newer one

  const runSearch = useCallback(async (q: string, opts?: { push?: boolean }) => {
    const trimmed = q.trim();
    if (!trimmed) return;
    // Shareable, back-button-friendly URL (?q=…). Skip the push when we're reacting to a
    // popstate or the initial load so we don't fight the history stack.
    if (opts?.push !== false) {
      const url = `/?q=${encodeURIComponent(trimmed)}`;
      if (window.location.search !== `?q=${encodeURIComponent(trimmed)}`) window.history.pushState({ q: trimmed }, "", url);
    }
    setQuery(trimmed);
    setError(null);
    setView("loading");
    const id = ++latest.current;
    setRefining(false);
    try {
      // 1) Instant keyword-ranked results (or the cached AI result, if this goal was searched recently)
      const quick = await api.search(trimmed, 4, true);
      if (id !== latest.current) return;
      setData(quick);
      setView("results");
      if (!quick.ai_pending) return;
      // 2) AI re-rank in the background; swap it in when it lands
      setRefining(true);
      try {
        const full = await api.search(trimmed, 4);
        if (id === latest.current) setData(full);
      } catch {
        /* keep the instant results if the AI pass fails */
      } finally {
        if (id === latest.current) setRefining(false);
      }
    } catch (e) {
      if (id !== latest.current) return;
      setError(e instanceof Error ? e.message : "Search failed");
      setView("home");
    }
  }, []);

  const home = useCallback(() => {
    setView("home"); setData(null);
    if (window.location.search) window.history.pushState({}, "", "/");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);
  const flash = useCallback((msg: string) => { setToast(msg); setTimeout(() => setToast(null), 2200); }, []);

  // Run a search from a ?q=... URL (shareable links + Google sitelinks search box), and keep
  // the view in sync with browser back/forward.
  useEffect(() => {
    const sync = () => {
      const q = new URLSearchParams(window.location.search).get("q");
      if (q) runSearch(q, { push: false });
      else { setView("home"); setData(null); }
    };
    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, [runSearch]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && view !== "home") home(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, home]);

  return (
    <>
      <Header
        showNew={view === "results" || view === "library"}
        onNew={home}
        onHome={home}
        onLibrary={() => setView("library")}
        onAuth={() => setAuthOpen(true)}
        onUpload={() => setUploadOpen(true)}
        onActivity={() => setActivityOpen(true)}
      />
      <main id="main">
        {view === "home" && <Home onSearch={runSearch} error={error} />}
        {view === "loading" && <Loading query={query} />}
        {view === "results" && data && <Results data={data} refining={refining} onCopy={flash} onPick={runSearch} onRequireAuth={() => setAuthOpen(true)} />}
        {view === "library" && <Library onCopy={flash} onPick={runSearch} />}
      </main>
      {view !== "loading" && <Footer />}
      {authOpen && <AuthModal onClose={() => setAuthOpen(false)} />}
      {uploadOpen && <UploadModal onClose={() => setUploadOpen(false)} onDone={flash} />}
      {activityOpen && <AdminActivity onClose={() => setActivityOpen(false)} />}
      <Toast message={toast} />
    </>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  );
}

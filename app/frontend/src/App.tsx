import { useCallback, useEffect, useState } from "react";
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

  const runSearch = useCallback(async (q: string) => {
    const trimmed = q.trim();
    if (!trimmed) return;
    setQuery(trimmed);
    setError(null);
    setView("loading");
    try {
      const [resp] = await Promise.all([api.search(trimmed, 4), new Promise((r) => setTimeout(r, 1800))]);
      setData(resp);
      setView("results");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed");
      setView("home");
    }
  }, []);

  const home = useCallback(() => { setView("home"); setData(null); window.scrollTo({ top: 0, behavior: "smooth" }); }, []);
  const flash = useCallback((msg: string) => { setToast(msg); setTimeout(() => setToast(null), 2200); }, []);

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
      />
      {view === "home" && <Home onSearch={runSearch} error={error} />}
      {view === "loading" && <Loading query={query} />}
      {view === "results" && data && <Results data={data} onCopy={flash} onPick={runSearch} onRequireAuth={() => setAuthOpen(true)} />}
      {view === "library" && <Library onCopy={flash} onPick={runSearch} />}
      {authOpen && <AuthModal onClose={() => setAuthOpen(false)} />}
      {uploadOpen && <UploadModal onClose={() => setUploadOpen(false)} onDone={flash} />}
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

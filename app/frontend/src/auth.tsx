import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setToken, getToken, type AuthUser } from "./api";

interface AuthCtx {
  user: AuthUser | null;
  ready: boolean;
  savedIds: Set<string>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  toggleSave: (id: string) => Promise<void>;
  isSaved: (id: string) => boolean;
}

const Ctx = createContext<AuthCtx | null>(null);
export const useAuth = () => {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside provider");
  return c;
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());

  const loadSaved = async () => {
    try { setSavedIds(new Set((await api.libraryIds()).ids)); } catch { setSavedIds(new Set()); }
  };

  // restore session on load
  useEffect(() => {
    (async () => {
      if (getToken()) {
        try { setUser(await api.me()); await loadSaved(); }
        catch { setToken(null); }
      }
      setReady(true);
    })();
  }, []);

  const afterAuth = async (r: { token: string; user: AuthUser }) => {
    setToken(r.token);
    setUser(r.user);
    await loadSaved();
  };

  const login = async (email: string, password: string) => afterAuth(await api.login(email, password));
  const register = async (email: string, password: string) => afterAuth(await api.register(email, password));
  const logout = () => { setToken(null); setUser(null); setSavedIds(new Set()); };

  const isSaved = (id: string) => savedIds.has(id);
  const toggleSave = async (id: string) => {
    if (!user) throw new Error("auth");
    const next = new Set(savedIds);
    if (next.has(id)) { next.delete(id); setSavedIds(next); await api.unsave(id); }
    else { next.add(id); setSavedIds(next); await api.save(id); }
  };

  return (
    <Ctx.Provider value={{ user, ready, savedIds, login, register, logout, toggleSave, isSaved }}>
      {children}
    </Ctx.Provider>
  );
}

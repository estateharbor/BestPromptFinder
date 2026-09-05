import type { SearchResponse, LeaderItem, PromptResult, Reliability, LibraryStats } from "./types";

// ---- token handling ----
let _token: string | null = null;
try { _token = localStorage.getItem("pf_token"); } catch { /* private mode */ }

export function setToken(t: string | null) {
  _token = t;
  try { t ? localStorage.setItem("pf_token", t) : localStorage.removeItem("pf_token"); } catch { /* ignore */ }
}
export function getToken() { return _token; }

function headers(json = true): Record<string, string> {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  if (_token) h["Authorization"] = `Bearer ${_token}`;
  return h;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `API ${res.status}`;
    try { const b = await res.json(); if (b?.detail) msg = b.detail; } catch { /* non-json */ }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export interface AuthUser { id: number; email: string; is_admin?: boolean; }
export interface AuthResult { token: string; user: AuthUser; }

export interface ActivityDay {
  date: string;
  pulled: number;
  graded: number;
  dropped: number;
  total: number;
  ai_graded: number;
  awaiting: number;
  grading_status?: string; // ok | out_of_credits | budget_exhausted | error | no_llm
  last_run?: string;
}
export interface ActivityResult { days: ActivityDay[]; last_refreshed: string | null; }

export interface IngestResult {
  read: number;
  added: number;
  curated?: number;
  queued_for_grading: number;
  skipped: number;
  reasons: Record<string, number>;
  added_titles: string[];
  message: string;
}

export const api = {
  async search(query: string, k = 4): Promise<SearchResponse> {
    return json(await fetch("/api/search", { method: "POST", headers: headers(), body: JSON.stringify({ query, k }) }));
  },
  async leaderboard(k = 5): Promise<{ results: LeaderItem[] }> {
    return json(await fetch(`/api/leaderboard?k=${k}`));
  },
  async stats(): Promise<LibraryStats> {
    return json(await fetch("/api/stats"));
  },
  async prompt(id: string): Promise<PromptResult> {
    return json(await fetch(`/api/prompt/${id}`, { headers: headers(false) }));
  },
  async previewStatus(): Promise<{ available: boolean }> {
    return json(await fetch("/api/preview/status"));
  },
  async preview(id: string): Promise<{ output: string; model: string }> {
    return json(await fetch("/api/preview", { method: "POST", headers: headers(), body: JSON.stringify({ id }) }));
  },
  async vote(id: string, verdict: "worked" | "didnt", model = ""): Promise<{ ok: boolean; reliability: Reliability }> {
    return json(await fetch("/api/vote", { method: "POST", headers: headers(), body: JSON.stringify({ id, verdict, model }) }));
  },

  // ---- auth ----
  async register(email: string, password: string): Promise<AuthResult> {
    return json(await fetch("/api/auth/register", { method: "POST", headers: headers(), body: JSON.stringify({ email, password }) }));
  },
  async login(email: string, password: string): Promise<AuthResult> {
    return json(await fetch("/api/auth/login", { method: "POST", headers: headers(), body: JSON.stringify({ email, password }) }));
  },
  async me(): Promise<AuthUser> {
    return json(await fetch("/api/me", { headers: headers(false) }));
  },

  // ---- admin: daily activity report ----
  async activity(): Promise<ActivityResult> {
    return json(await fetch("/api/admin/activity", { headers: headers(false) }));
  },

  // ---- admin: upload/ingest an Excel/CSV of prompts ----
  async ingest(file: File): Promise<IngestResult> {
    const fd = new FormData();
    fd.append("file", file);
    // Don't set Content-Type — the browser adds the multipart boundary itself.
    const h: Record<string, string> = {};
    if (_token) h["Authorization"] = `Bearer ${_token}`;
    return json(await fetch("/api/ingest", { method: "POST", headers: h, body: fd }));
  },

  // ---- library ----
  async library(): Promise<{ count: number; results: PromptResult[] }> {
    return json(await fetch("/api/library", { headers: headers(false) }));
  },
  async libraryIds(): Promise<{ ids: string[] }> {
    return json(await fetch("/api/library/ids", { headers: headers(false) }));
  },
  async save(id: string): Promise<{ saved: boolean }> {
    return json(await fetch("/api/library", { method: "POST", headers: headers(), body: JSON.stringify({ id }) }));
  },
  async unsave(id: string): Promise<{ saved: boolean }> {
    return json(await fetch(`/api/library/${id}`, { method: "DELETE", headers: headers(false) }));
  },
};

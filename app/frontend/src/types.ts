export interface Scores {
  quality: number;
  match: number;
  reliability: number;
  freshness: number;
  overall: number;
}

export interface Reliability {
  uses: number;
  useful: number;
  tested: string[];
  last_verified: string;
  score: number;
  worked: number;
  didnt: number;
  votes: number;
  source: "votes" | "seeded";
}

export interface Provenance {
  source: string;
  url: string;
  collected: string;
  version: string;
  eval_source: string;
}

export interface PromptResult {
  id: string;
  title: string;
  prompt: string;
  template: string;
  variables: string[];
  is_template: boolean;
  prompt_type: string;
  purpose: string;
  platform: string;
  models: string[];
  scores: Scores;
  reliability: Reliability;
  why: string[];
  weakness: string;
  match_source: "llm" | "heuristic";
  provenance: Provenance;
}

export interface Intent {
  purpose: string;
  prompt_type: string;
  query: string;
}

export interface SearchResponse {
  intent: Intent;
  count: number;
  enriched: boolean;
  results: PromptResult[];
}

export interface LibraryStats {
  total: number;
  by_platform: Record<string, number>;
  by_purpose: Record<string, number>;
  by_type: Record<string, number>;
  eval_source: Record<string, number>;
  last_refreshed: string | null;
  votes: number;
}

export interface LeaderItem {
  id: string;
  title: string;
  purpose: string;
  uses: number;
  useful: number;
  reliability: number;
  votes: number;
  source: "votes" | "seeded";
  models: string[];
}

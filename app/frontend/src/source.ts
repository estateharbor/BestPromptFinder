// Maps a raw provenance source/url to a clean, user-facing category label.
// Keeps the real URL available as a click-through so attribution is preserved
// without showing users a wall of competitor/blog links.

export interface SourceLabel {
  label: string;
  url?: string; // present only when there's a real link to attribute to
}

const OFFICIAL = [
  "anthropic.com", "claude.com", "openai.com", "blog.google", "google.com",
  "microsoft.com", "learn.microsoft", "adobe.com", "jetbrains.com",
  "linkedin.com", "hubspot.com",
];

export function sourceLabel(source: string, url?: string): SourceLabel {
  const s = (source || "").toLowerCase();
  const u = (url || "").toLowerCase();
  const link = /^https?:\/\//.test(url || "") ? url : undefined;
  const inUrl = (...xs: string[]) => xs.some((x) => u.includes(x));

  // Platform-scraped sources map straight to a category.
  if (s.includes("hugging face")) return { label: "Dataset", url: link };
  if (s.includes("gpt-image") || s.includes("gallery") || s.includes("prompthero"))
    return { label: "Gallery", url: link };
  if (s.includes("hacker news") || s.includes("prompt index")) return { label: "Community", url: link };
  if (s === "github") return { label: "GitHub", url: link };

  // Curated / uploaded / llm-curated: classify by the real origin URL when we have one,
  // so an admin upload from official docs reads "Official", from a blog reads "Community".
  if (inUrl(...OFFICIAL)) return { label: "Official", url: link };
  if (inUrl("github.com")) return { label: "GitHub", url: link };
  if (inUrl("reddit.com", "medium.com", "substack")) return { label: "Community", url: link };
  if (link) return { label: "Community", url: link };

  // No usable link → an editorial / hand-curated entry.
  return { label: "Curated" };
}

// Maps a raw provenance source/url to a clean, user-facing source label.
// The label is derived from the actual link's domain whenever a link exists, so the label
// can never contradict where it points (e.g. an Adobe Firefly URL never reads "Official").

export interface SourceLabel {
  label: string;
  url?: string; // present only when there's a real link to attribute to
}

// domain fragment -> brand shown to the user. Order matters (more specific first).
const BRANDS: [string, string][] = [
  ["anthropic.com", "Anthropic"], ["claude.com", "Anthropic"],
  ["openai.com", "OpenAI"], ["chatgpt.com", "OpenAI"],
  ["firefly.adobe", "Adobe Firefly"], ["adobe.com", "Adobe"],
  ["deepmind.google", "Google DeepMind"], ["blog.google", "Google"],
  ["ai.google", "Google"], ["gemini.google", "Google"], ["labs.google", "Google Labs"],
  ["google.com", "Google"],
  ["learn.microsoft", "Microsoft"], ["microsoft.com", "Microsoft"],
  ["jetbrains.com", "JetBrains"], ["hubspot.com", "HubSpot"],
  ["github.com", "GitHub"], ["huggingface.co", "Hugging Face"],
  ["prompthero.com", "PromptHero"], ["reddit.com", "Reddit"],
  ["medium.com", "Medium"], ["substack.com", "Substack"],
  ["linkedin.com", "LinkedIn"], ["news.ycombinator.com", "Hacker News"],
];

export function sourceLabel(source: string, url?: string): SourceLabel {
  const s = (source || "").toLowerCase();
  const u = (url || "").toLowerCase();
  const link = /^https?:\/\//.test(url || "") ? url : undefined;

  // 1) With a real link, the label is the brand of that exact domain — label and destination
  //    are always consistent. Falls back to the bare hostname for unknown domains.
  if (link) {
    for (const [frag, name] of BRANDS) if (u.includes(frag)) return { label: name, url: link };
    try {
      return { label: new URL(link).hostname.replace(/^www\./, ""), url: link };
    } catch {
      return { label: "Source", url: link };
    }
  }

  // 2) No link → classify the scraped platform name into a neutral category.
  if (s.includes("hugging face")) return { label: "Dataset" };
  if (s.includes("gpt-image") || s.includes("gallery") || s.includes("prompthero")) return { label: "Gallery" };
  if (s.includes("hacker news") || s.includes("prompt index")) return { label: "Community" };
  if (s === "github") return { label: "GitHub" };
  return { label: "Curated" };
}

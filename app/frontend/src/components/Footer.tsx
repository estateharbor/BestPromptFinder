// Sitewide footer — links to the crawlable, server-rendered info/policy pages (these are
// real routes served by the backend, so a full page load lands on proper content).
const LINKS: [string, string][] = [
  ["Browse", "/browse"],
  ["About", "/about"],
  ["How scoring works", "/methodology"],
  ["Content & source policy", "/source-policy"],
  ["Submit a prompt", "/submit"],
  ["Privacy", "/privacy"],
  ["Terms", "/terms"],
  ["Contact", "mailto:support@bestpromptfinder.com"],
];

export function Footer() {
  return (
    <footer
      className="mt-8 border-t"
      style={{
        borderColor: "var(--color-hairline)",
        paddingBottom: "calc(env(safe-area-inset-bottom) + 20px)",
      }}
    >
      <div className="max-w-[920px] mx-auto px-6 pt-6 flex flex-col gap-2.5">
        <nav className="flex flex-wrap gap-x-4 gap-y-2">
          {LINKS.map(([label, href]) => (
            <a key={href} href={href} className="font-mono text-[12.5px]"
              style={{ color: "var(--color-ink2)" }}>{label}</a>
          ))}
        </nav>
        <p className="font-mono text-[11px]" style={{ color: "var(--color-ink3)" }}>
          © {new Date().getFullYear()} BestPromptFinder — the free AI prompt decision engine.
          Scores are AI evaluations, not user ratings. Not financial, legal or investment advice.
        </p>
      </div>
    </footer>
  );
}

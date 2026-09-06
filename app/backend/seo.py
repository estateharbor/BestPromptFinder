"""
Server-rendered SEO pages — real HTML (content + meta + JSON-LD) for each prompt and
category, plus a dynamic sitemap. Crawlers and AI answer engines read these directly
without running JavaScript; human visitors get the content plus a link into the app.
"""
import html as _html
import json as _json
import re
from typing import Any, Dict, List
from urllib.parse import quote

SITE = "https://bestpromptfinder.com"


def esc(s: Any) -> str:
    return _html.escape(str(s if s is not None else ""), quote=True)


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "other"


def category_slug_map(corpus: List[Dict[str, Any]]) -> Dict[str, str]:
    """slug -> canonical purpose name."""
    m: Dict[str, str] = {}
    for c in corpus:
        p = (c.get("purpose") or "Other").strip()
        m.setdefault(slugify(p), p)
    return m


def _page(title: str, description: str, canonical: str, body: str, jsonld: Any = None) -> str:
    ld = f'<script type="application/ld+json">{_json.dumps(jsonld, ensure_ascii=False)}</script>' if jsonld else ""
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="BestPromptFinder">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(canonical)}"><meta property="og:image" content="{SITE}/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}"><meta name="twitter:image" content="{SITE}/og-image.png">
<link rel="icon" type="image/png" href="/icon-192.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<style>
:root{{color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;background:#0e131b;color:#eaeef4;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;line-height:1.6}}
a{{color:#aab8ff}}
.wrap{{max-width:760px;margin:0 auto;padding:20px 24px 60px}}
header a.brand{{display:inline-flex;align-items:center;gap:8px;font-weight:800;color:#fff;text-decoration:none;font-size:18px}}
header img{{height:26px;width:auto}}
.crumb{{font-size:13px;color:#8a93a5;margin:20px 0}}
.crumb a{{color:#8a93a5}}
h1{{font-size:1.85rem;line-height:1.2;margin:.15em 0 .3em}}
h2{{font-size:1.15rem;margin:1.6em 0 .5em}}
.meta{{color:#aab8ff;font-family:ui-monospace,SFMono-Regular,monospace;font-size:13px}}
.scores{{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}}
.score{{background:#161d28;border:1px solid #26303f;border-radius:10px;padding:8px 14px;font-size:12px;color:#8a93a5;text-align:center}}
.score b{{display:block;font-size:18px;color:#7b90ff;margin-bottom:2px}}
pre{{background:#161d28;border:1px solid #26303f;border-radius:12px;padding:16px;white-space:pre-wrap;word-wrap:break-word;font-size:13.5px;overflow-x:auto}}
.btn{{display:inline-block;background:#2e4bd8;color:#fff;text-decoration:none;font-weight:700;padding:10px 18px;border-radius:11px;margin:10px 10px 0 0;border:none;cursor:pointer;font-size:14px}}
.btn.ghost{{background:#161d28;border:1px solid #26303f;color:#eaeef4}}
ul.hl{{padding-left:20px}} ul.hl li{{margin:4px 0}}
.card{{display:block;background:#161d28;border:1px solid #26303f;border-radius:12px;padding:14px 16px;margin:10px 0;text-decoration:none;color:inherit}}
.card:hover{{border-color:#2e4bd8}}
.card b{{color:#fff;font-size:15px}} .card .s{{color:#8a93a5;font-size:12.5px;font-family:ui-monospace,monospace}}
footer{{margin:44px 0 0;color:#8a93a5;font-size:13px;border-top:1px solid #26303f;padding-top:18px}}
</style>
{ld}
</head><body><div class="wrap">
<header><a class="brand" href="/"><img src="/logo-mark.png" alt="">BestPromptFinder</a></header>
{body}
<footer>© BestPromptFinder — the free AI prompt decision engine. <a href="/">Search 1,000+ ranked prompts →</a></footer>
</div></body></html>"""


def _highlights(p: Dict[str, Any]) -> str:
    items = []
    src = p.get("provenance", {}).get("eval_source")
    if src == "curated":
        items.append("Hand-picked, editorially reviewed prompt")
    elif src == "llm" and p.get("quality") is not None:
        items.append(f"AI-graded {p.get('quality')}/100 for quality and structure")
    if p.get("is_template") and p.get("variables"):
        items.append("Reusable template — swap in " + ", ".join("{" + v + "}" for v in p["variables"][:6]))
    rel = p.get("reliability", {})
    if rel.get("useful"):
        items.append(f"{rel['useful']}% found it useful across {', '.join(p.get('models') or ['multiple models'])}")
    if not items:
        return ""
    return "<h2>Why this prompt</h2><ul class='hl'>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def prompt_page(p: Dict[str, Any], related: List[Dict[str, Any]], cat_slug: str) -> str:
    purpose = p.get("purpose") or "Other"
    title = f"{p['title']} — {purpose} AI Prompt | BestPromptFinder"
    desc = re.sub(r"\s+", " ", (p.get("prompt") or ""))[:155]
    canonical = f"{SITE}/prompt/{p['id']}"
    models = ", ".join(p.get("models") or [])
    rel = p.get("reliability", {})
    scores = f"""<div class="scores">
      <div class="score"><b>{esc(p.get('quality',''))}</b>Quality</div>
      <div class="score"><b>{esc(rel.get('useful',''))}%</b>Useful</div>
      <div class="score"><b>{esc(rel.get('reliability',''))}</b>Reliability</div>
    </div>"""
    related_html = ""
    if related:
        cards = "".join(
            f'<a class="card" href="/prompt/{esc(r["id"])}"><b>{esc(r["title"])}</b><br>'
            f'<span class="s">Quality {esc(r.get("quality",""))} · {esc(", ".join(r.get("models") or []))}</span></a>'
            for r in related)
        related_html = f"<h2>Related {esc(purpose)} prompts</h2>{cards}"
    src = p.get("provenance", {})
    src_html = ""
    if src.get("url"):
        src_html = f'<h2>Source</h2><p><a href="{esc(src["url"])}" rel="nofollow noopener" target="_blank">{esc(src.get("source") or "View source")}</a></p>'
    body = f"""
<div class="crumb"><a href="/">Home</a> › <a href="/category/{esc(cat_slug)}">{esc(purpose)}</a> › {esc(p['title'])}</div>
<h1>{esc(p['title'])}</h1>
<div class="meta">{esc(purpose)} · {esc(models)} · {esc(p.get('prompt_type',''))}</div>
{scores}
<h2>The prompt</h2>
<pre id="prompt">{esc(p.get('prompt'))}</pre>
<button class="btn" onclick="navigator.clipboard.writeText(document.getElementById('prompt').innerText);this.textContent='Copied!'">Copy prompt</button>
<a class="btn ghost" href="/?q={quote(p['title'])}">Find similar in the app →</a>
{_highlights(p)}
{src_html}
{related_html}
"""
    jsonld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "CreativeWork", "name": p["title"], "text": p.get("prompt"),
                "url": canonical, "about": purpose, "isAccessibleForFree": True,
                "inLanguage": "en", "creator": {"@type": "Organization", "name": "BestPromptFinder", "url": SITE + "/"},
            },
            {
                "@type": "BreadcrumbList", "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"},
                    {"@type": "ListItem", "position": 2, "name": purpose, "item": f"{SITE}/category/{cat_slug}"},
                    {"@type": "ListItem", "position": 3, "name": p["title"], "item": canonical},
                ],
            },
        ],
    }
    return _page(title, desc, canonical, body, jsonld)


def category_page(cat: str, slug: str, prompts: List[Dict[str, Any]]) -> str:
    title = f"Best {cat} AI Prompts ({len(prompts)}) | BestPromptFinder"
    desc = f"{len(prompts)} ranked, AI-graded {cat} prompts for ChatGPT, Claude, Gemini and Midjourney. Find the best {cat} prompt for your goal — free."
    canonical = f"{SITE}/category/{slug}"
    shown = prompts[:150]
    cards = "".join(
        f'<a class="card" href="/prompt/{esc(p["id"])}"><b>{esc(p["title"])}</b><br>'
        f'<span class="s">Quality {esc(p.get("quality",""))} · {esc(", ".join(p.get("models") or []))}</span></a>'
        for p in shown)
    body = f"""
<div class="crumb"><a href="/">Home</a> › {esc(cat)}</div>
<h1>Best {esc(cat)} AI Prompts</h1>
<p>{len(prompts)} ranked, AI-graded {esc(cat)} prompts for ChatGPT, Claude, Gemini and Midjourney. Open any prompt to view it in full, or <a href="/?q={quote(cat)}">search for your exact goal in the app</a>.</p>
{cards}
"""
    jsonld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "CollectionPage", "name": f"Best {cat} AI Prompts", "url": canonical,
                "description": desc,
                "mainEntity": {
                    "@type": "ItemList", "numberOfItems": len(shown),
                    "itemListElement": [
                        {"@type": "ListItem", "position": i + 1, "url": f"{SITE}/prompt/{p['id']}", "name": p["title"]}
                        for i, p in enumerate(shown)
                    ],
                },
            },
            {
                "@type": "BreadcrumbList", "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"},
                    {"@type": "ListItem", "position": 2, "name": cat, "item": canonical},
                ],
            },
        ],
    }
    return _page(title, desc, canonical, body, jsonld)


def sitemap(corpus: List[Dict[str, Any]], cat_slugs: List[str]) -> str:
    urls = [f"{SITE}/"] + [f"{SITE}/category/{s}" for s in cat_slugs] + [f"{SITE}/prompt/{c['id']}" for c in corpus]
    body = "".join(f"<url><loc>{esc(u)}</loc></url>" for u in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'

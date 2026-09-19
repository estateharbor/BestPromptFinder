"""
Server-rendered SEO pages — real HTML (content + meta + JSON-LD) for each prompt and
category, plus a dynamic sitemap. Crawlers and AI answer engines read these directly
without running JavaScript; human visitors get the content plus a link into the app.
"""
import html as _html
import json as _json
import os
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote

SITE = "https://bestpromptfinder.com"

# How many prompt pages to keep indexable. Google favours a smaller set of unique, tested
# pages over thousands of thin ones — the rest are noindex,follow (usable in-app, not in
# search) and excluded from the sitemap. Tune via SEO_INDEX_LIMIT.
INDEX_LIMIT = int(os.getenv("SEO_INDEX_LIMIT", "150"))

_CJK = re.compile(r"[　-〿぀-ヿ㐀-䶿一-鿿가-힯＀-￯]")

ROBOTS_INDEX = "index, follow, max-image-preview:large, max-snippet:-1"
ROBOTS_NOINDEX = "noindex, follow"


def esc(s: Any) -> str:
    return _html.escape(str(s if s is not None else ""), quote=True)


def is_english(*texts: str) -> bool:
    """True unless the text carries CJK (Chinese/Japanese/Korean) characters — used to keep
    English category pages English by default."""
    return not any(_CJK.search(t or "") for t in texts)


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "other"


# Prompt ids are "p_" + hex (content hash). Descriptive URLs are "{title-slug}-{id}", which
# stay unique and permanently stable even if two prompts share a title or the corpus reorders.
_ID_RE = re.compile(r"(p_[0-9a-f]+)$")


def prompt_slug(p: Dict[str, Any]) -> str:
    base = slugify(p.get("title") or "")[:60].strip("-") or "prompt"
    return f"{base}-{p['id']}"


def prompt_path(p: Dict[str, Any]) -> str:
    return f"/prompt/{prompt_slug(p)}"


def key_to_id(key: str) -> str:
    """Recover the prompt id from a URL key — works for both a descriptive slug
    ('equity-earnings-analyst-p_03d5c4c278') and a bare legacy id ('p_03d5c4c278')."""
    m = _ID_RE.search(key or "")
    return m.group(1) if m else ""


def tier_a_ids(corpus: List[Dict[str, Any]]) -> Set[str]:
    """The set of prompt ids worth indexing: English, editorially/AI-evaluated, substantial,
    and top-quality — capped at INDEX_LIMIT. Everything else is noindex,follow."""
    eligible = [
        c for c in corpus
        if is_english(c.get("title"), c.get("prompt"))
        and (c.get("provenance") or {}).get("eval_source") in ("curated", "llm")
        and len(c.get("prompt") or "") >= 200
        and c.get("quality")
    ]
    eligible.sort(key=lambda c: c.get("quality", 0), reverse=True)
    return {c["id"] for c in eligible[:INDEX_LIMIT]}


def category_slug_map(corpus: List[Dict[str, Any]]) -> Dict[str, str]:
    """slug -> canonical purpose name."""
    m: Dict[str, str] = {}
    for c in corpus:
        p = (c.get("purpose") or "Other").strip()
        m.setdefault(slugify(p), p)
    return m


def _page(title: str, description: str, canonical: str, body: str, jsonld: Any = None,
          robots: str = ROBOTS_INDEX, head_extra: str = "") -> str:
    ld = f'<script type="application/ld+json">{_json.dumps(jsonld, ensure_ascii=False)}</script>' if jsonld else ""
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="robots" content="{esc(robots)}">{head_extra}
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
.crumb{{font-size:13px;color:#9aa4b5;margin:20px 0}}
.crumb a{{color:#9aa4b5}}
nav.top{{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-left:auto;font-size:13px}}
nav.top a{{color:#c3ccdb;text-decoration:none}}
nav.top form{{display:flex;gap:6px}}
nav.top input{{background:#0e131b;border:1px solid #26303f;border-radius:9px;padding:7px 11px;color:#eaeef4;font-size:13px;min-width:150px}}
nav.top button{{background:#2e4bd8;border:none;color:#fff;border-radius:9px;padding:7px 13px;font-weight:700;cursor:pointer;font-size:13px}}
.hdr{{display:flex;align-items:center;gap:16px;flex-wrap:wrap}}
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
.card b{{color:#fff;font-size:15px}} .card .s{{color:#9aa4b5;font-size:12.5px;font-family:ui-monospace,monospace}}
.card .desc{{color:#c3ccdb;font-size:13px;display:inline-block;margin:5px 0 2px}}
.filters{{margin:18px 0 8px}}
.filters input{{width:100%;background:#0e131b;border:1px solid #26303f;border-radius:10px;padding:10px 13px;color:#eaeef4;font-size:14px}}
.chips{{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}}
.chip{{background:#161d28;border:1px solid #26303f;color:#c3ccdb;border-radius:999px;padding:6px 13px;font-size:12.5px;cursor:pointer}}
.chip.on{{background:#2e4bd8;border-color:#2e4bd8;color:#fff}}
footer{{margin:44px 0 0;color:#9aa4b5;font-size:13px;border-top:1px solid #26303f;padding-top:18px}}
footer a{{color:#aab8ff}}
</style>
{ld}
</head><body><main class="wrap">
<header class="hdr"><a class="brand" href="/"><img src="/logo-mark.png" alt="">BestPromptFinder</a>
<nav class="top"><a href="/">Home</a><a href="{SITE}/sitemap.xml">All prompts</a>
<form action="/" method="get" role="search"><input type="search" name="q" placeholder="Describe your goal…" aria-label="Search prompts"><button type="submit">Find</button></form></nav></header>
{body}
<footer>© BestPromptFinder — the free AI prompt decision engine. <a href="/">Search ranked, AI-graded prompts →</a></footer>
</main></body></html>"""


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


def prompt_page(p: Dict[str, Any], related: List[Dict[str, Any]], cat_slug: str,
                indexable: bool = True) -> str:
    purpose = p.get("purpose") or "Other"
    title = f"{p['title']} — {purpose} AI Prompt | BestPromptFinder"
    desc = re.sub(r"\s+", " ", (p.get("prompt") or ""))[:155]
    canonical = f"{SITE}{prompt_path(p)}"
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
            f'<a class="card" href="{esc(prompt_path(r))}"><b>{esc(r["title"])}</b><br>'
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
    # Only Tier-A pages advertise a rich-result CreativeWork and ask to be indexed; the long
    # tail is noindex,follow (still reachable in-app, just not competing in search).
    return _page(title, desc, canonical, body,
                 jsonld=jsonld if indexable else None,
                 robots=ROBOTS_INDEX if indexable else ROBOTS_NOINDEX)


def category_page(cat: str, slug: str, prompts: List[Dict[str, Any]]) -> str:
    # English-only by default so English category pages don't mix in CJK-language prompts.
    prompts = [p for p in prompts if is_english(p.get("title"), p.get("prompt"))]
    title = f"Best {cat} AI Prompts ({len(prompts)}) | BestPromptFinder"
    desc = f"{len(prompts)} ranked, AI-graded {cat} prompts for ChatGPT, Claude, Gemini and Midjourney. Find the best {cat} prompt for your goal — free."
    canonical = f"{SITE}/category/{slug}"
    shown = prompts[:150]

    # Models present in this category → filter chips (client-side show/hide, no framework).
    model_set: List[str] = []
    for p in shown:
        for m in (p.get("models") or []):
            if m not in model_set:
                model_set.append(m)
    chips = '<button class="chip on" data-model="all">All models</button>' + "".join(
        f'<button class="chip" data-model="{esc(m)}">{esc(m)}</button>' for m in model_set[:8])

    def _snippet(p: Dict[str, Any]) -> str:
        s = re.sub(r"\s+", " ", (p.get("prompt") or "")).strip()
        return esc(s[:120] + ("…" if len(s) > 120 else ""))

    cards = "".join(
        f'<a class="card" data-models="{esc("|".join(p.get("models") or []))}" data-title="{esc((p.get("title") or "").lower())}" href="{esc(prompt_path(p))}">'
        f'<b>{esc(p["title"])}</b><br>'
        f'<span class="desc">{_snippet(p)}</span><br>'
        f'<span class="s">Quality {esc(p.get("quality",""))} · {esc(", ".join(p.get("models") or []))}</span></a>'
        for p in shown)

    filters = f"""
<div class="filters">
  <input id="catq" type="search" placeholder="Filter these {len(shown)} prompts…" aria-label="Filter prompts">
  <div class="chips">{chips}</div>
</div>"""
    filter_js = """
<script>
(function(){
  var q=document.getElementById('catq'),chips=document.querySelectorAll('.chip'),cards=document.querySelectorAll('.card[data-models]');
  var model='all';
  function apply(){var t=(q.value||'').toLowerCase();cards.forEach(function(c){
    var okM=model==='all'||('|'+c.dataset.models+'|').indexOf('|'+model+'|')>=0;
    var okT=!t||c.dataset.title.indexOf(t)>=0||c.textContent.toLowerCase().indexOf(t)>=0;
    c.style.display=(okM&&okT)?'block':'none';});}
  q.addEventListener('input',apply);
  chips.forEach(function(ch){ch.addEventListener('click',function(){chips.forEach(function(x){x.classList.remove('on');});ch.classList.add('on');model=ch.dataset.model;apply();});});
})();
</script>"""
    body = f"""
<div class="crumb"><a href="/">Home</a> › {esc(cat)}</div>
<h1>Best {esc(cat)} AI Prompts</h1>
<p>{len(prompts)} ranked, AI-graded {esc(cat)} prompts for ChatGPT, Claude, Gemini and Midjourney. Open any prompt to view it in full, or <a href="/?q={quote(cat)}">search for your exact goal in the app</a>.</p>
{filters}
{cards}
{filter_js}
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
                        {"@type": "ListItem", "position": i + 1, "url": f"{SITE}{prompt_path(p)}", "name": p["title"]}
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


def _lastmod(c: Dict[str, Any]) -> str:
    """Best available date for a prompt, as YYYY-MM-DD (day defaults to 01 when unknown)."""
    d = (c.get("reliability") or {}).get("last_verified") or (c.get("provenance") or {}).get("collected") or ""
    m = re.match(r"(\d{4})-(\d{2})(?:-(\d{2}))?", str(d))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3) or '01'}" if m else ""


def sitemap(corpus: List[Dict[str, Any]], cat_slugs: List[str],
            index_ids: Optional[Set[str]] = None) -> str:
    """Sitemap of the homepage, categories, and only the indexable (Tier-A) prompt pages —
    each with a <lastmod>. Passing index_ids=None includes every prompt (legacy behaviour)."""
    prompts = [c for c in corpus if index_ids is None or c["id"] in index_ids]
    rows = [(f"{SITE}/", "")] + [(f"{SITE}/category/{s}", "") for s in cat_slugs]
    rows += [(f"{SITE}{prompt_path(c)}", _lastmod(c)) for c in prompts]
    body = "".join(
        f"<url><loc>{esc(u)}</loc>{f'<lastmod>{lm}</lastmod>' if lm else ''}</url>" for u, lm in rows)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'

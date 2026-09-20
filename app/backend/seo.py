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
<nav class="top"><a href="/">Home</a><a href="/browse">Browse</a>
<form action="/" method="get" role="search"><input type="search" name="q" placeholder="Describe your goal…" aria-label="Search prompts"><button type="submit">Find</button></form></nav></header>
{body}
<footer>
<p>© BestPromptFinder — the free AI prompt decision engine. Scores are AI evaluations, not user ratings.</p>
<p><a href="/browse">Browse</a> · <a href="/about">About</a> · <a href="/methodology">How scoring works</a> · <a href="/source-policy">Content &amp; source policy</a> · <a href="/submit">Submit a prompt</a> · <a href="/privacy">Privacy</a> · <a href="/terms">Terms</a> · <a href="mailto:support@bestpromptfinder.com">Contact</a></p>
</footer>
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
    if p.get("models"):
        items.append("Written for " + ", ".join(p["models"]))
    # NOTE: no "X% found it useful" claim — these figures are AI estimates, not user votes.
    if not items:
        return ""
    return "<h2>Why this prompt</h2><ul class='hl'>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def _attribution(p: Dict[str, Any]) -> str:
    """Honest source + licence block. Third-party prompts show origin, dataset/author, licence
    (or an explicit 'not stated'), whether adapted, and the import date. Editorial prompts say
    so plainly — never an unsupported 'source linked above'."""
    prov = p.get("provenance") or {}
    raw = (prov.get("url") or "").strip()
    url, _, note = raw.partition(" ")          # curated urls are stored as "https://… (MIT)"
    imported = esc(prov.get("collected") or "")
    src_name = esc(prov.get("source") or "")
    if url.startswith("http"):
        try:
            host = url.split("/")[2].replace("www.", "")
        except Exception:
            host = "original source"
        lic = note.strip("() ").strip()
        lic_li = (f"<li><b>Licence:</b> {esc(lic)}</li>" if lic else
                  "<li><b>Licence:</b> Not stated by the source. Review the original source terms before commercial reuse.</li>")
        return ("<h2>Source &amp; licence</h2><ul class='hl'>"
                f'<li><b>Original source:</b> <a href="{esc(url)}" rel="nofollow noopener" target="_blank">{esc(host)} ↗</a></li>'
                f"<li><b>Author / dataset:</b> {src_name or esc(host)}</li>"
                f"{lic_li}"
                "<li><b>Adapted:</b> Imported unmodified.</li>"
                f"{f'<li><b>Imported:</b> {imported}</li>' if imported else ''}"
                "</ul>")
    return ('<h2>Source</h2><p>Created by BestPromptFinder — editorial prompt, not user-generated. '
            'See our <a href="/source-policy">content &amp; source policy</a>.</p>')


def prompt_page(p: Dict[str, Any], related: List[Dict[str, Any]], cat_slug: str,
                indexable: bool = True) -> str:
    purpose = p.get("purpose") or "Other"
    title = f"{p['title']} — {purpose} AI Prompt | BestPromptFinder"
    desc = re.sub(r"\s+", " ", (p.get("prompt") or ""))[:155]
    canonical = f"{SITE}{prompt_path(p)}"
    models = ", ".join(p.get("models") or [])
    rel = p.get("reliability", {})
    scores = f"""<div class="scores">
      <div class="score"><b>{esc(p.get('quality',''))}</b>AI Quality /100</div>
      <div class="score"><b>{esc(rel.get('useful',''))}</b>AI Usefulness est. /100</div>
      <div class="score"><b>{esc(rel.get('reliability',''))}</b>Eval Confidence /100</div>
      <div class="score"><b>No votes yet</b>Community results</div>
    </div>
    <p class="meta" style="margin-top:-4px">Quality, usefulness and confidence are AI evaluations out of 100 — not user ratings. Community results appear once visitors vote. <a href="/methodology">How scoring works →</a></p>"""
    related_html = ""
    if related:
        cards = "".join(
            f'<a class="card" href="{esc(prompt_path(r))}"><b>{esc(r["title"])}</b><br>'
            f'<span class="s">Quality {esc(r.get("quality",""))} · {esc(", ".join(r.get("models") or []))}</span></a>'
            for r in related)
        related_html = f"<h2>Related {esc(purpose)} prompts</h2>{cards}"
    src_html = _attribution(p)
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
    rows = [(f"{SITE}/", ""), (f"{SITE}/browse", "")]
    rows += [(f"{SITE}/{s}", "") for s in ("about", "methodology", "source-policy", "submit", "privacy", "terms")]
    rows += [(f"{SITE}/category/{s}", "") for s in cat_slugs]
    rows += [(f"{SITE}{prompt_path(c)}", _lastmod(c)) for c in prompts]
    body = "".join(
        f"<url><loc>{esc(u)}</loc>{f'<lastmod>{lm}</lastmod>' if lm else ''}</url>" for u, lm in rows)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'


def browse_page(corpus: List[Dict[str, Any]], cat_map: Dict[str, str]) -> str:
    """Human-facing browse hub: search box, category grid with counts, and top-rated
    prompts. (sitemap.xml stays machine-only.)"""
    from collections import Counter
    counts = Counter((c.get("purpose") or "Other") for c in corpus)
    cats = sorted(cat_map.items(), key=lambda kv: counts.get(kv[1], 0), reverse=True)
    cat_cards = "".join(
        f'<a class="card" href="/category/{esc(slug)}"><b>{esc(name)}</b><br>'
        f'<span class="s">{counts.get(name, 0)} prompts</span></a>'
        for slug, name in cats)
    english = [c for c in corpus if is_english(c.get("title"), c.get("prompt")) and c.get("quality")]
    top = sorted(english, key=lambda c: c.get("quality", 0), reverse=True)[:24]
    top_cards = "".join(
        f'<a class="card" href="{esc(prompt_path(c))}"><b>{esc(c["title"])}</b><br>'
        f'<span class="s">AI Quality {esc(c.get("quality",""))} · {esc(c.get("purpose",""))}</span></a>'
        for c in top)
    body = f"""
<div class="crumb"><a href="/">Home</a> &rsaquo; Browse</div>
<h1>Browse AI prompts</h1>
<p>Explore {len(corpus)} ranked, AI-graded prompts by category, or describe your goal to get a matched recommendation. Scores are AI evaluations out of 100, not user ratings &mdash; see <a href="/methodology">how scoring works</a>.</p>
<div class="filters"><form action="/" method="get" role="search"><input type="search" name="q" placeholder="Describe your goal - e.g. facebook ad for a commercial property" aria-label="Search prompts"></form></div>
<h2>Categories</h2>
{cat_cards}
<h2>Top-rated prompts</h2>
{top_cards}
"""
    jsonld = {"@context": "https://schema.org", "@type": "CollectionPage",
              "name": "Browse AI Prompts", "url": f"{SITE}/browse",
              "description": "Browse ranked, AI-graded AI prompts by category."}
    return _page("Browse AI Prompts - Categories & Top Rated | BestPromptFinder",
                 "Browse ranked, AI-graded AI prompts by category, model and quality. Free.",
                 f"{SITE}/browse", body, jsonld)


def _info(title: str, slug: str, desc: str, html_body: str) -> str:
    body = f'<div class="crumb"><a href="/">Home</a> &rsaquo; {esc(title)}</div><h1>{esc(title)}</h1>{html_body}'
    return _page(f"{title} | BestPromptFinder", desc, f"{SITE}/{slug}", body)


INFO_PAGES = {
    "about": ("About BestPromptFinder",
              "What BestPromptFinder is, who it is for, and how it is different.", """
<p>BestPromptFinder is a free prompt <strong>decision engine</strong>. Instead of browsing a directory of thousands of prompts, you describe your goal in plain words and we rank the prompts most likely to solve it - showing an AI quality score, goal-match and evaluation confidence before you run one.</p>
<h2>Who it is for</h2>
<p>Founders, marketers, analysts, agents and operators who want a tested, ready-to-run prompt for a specific job, across ChatGPT, Claude, Gemini and Midjourney.</p>
<h2>How we are different</h2>
<ul class="hl">
<li>Goal-first matching, not keyword browsing.</li>
<li>Every prompt shows why it fits and where it falls short.</li>
<li>Transparent scoring - AI evaluations are labelled as estimates, never disguised as user votes. See our <a href="/methodology">methodology</a>.</li>
<li>Sourcing is disclosed: editorial prompts say so; third-party prompts link the original and licence.</li>
</ul>
<p>Questions or corrections: <a href="mailto:support@bestpromptfinder.com">support@bestpromptfinder.com</a>.</p>"""),

    "methodology": ("How scoring works",
                    "How BestPromptFinder scores prompts: AI quality, usefulness, confidence and community votes.", """
<p>Every score on this site is an <strong>AI evaluation out of 100</strong> unless it is explicitly labelled as a community result. We never present an AI estimate as a user rating.</p>
<h2>The scores</h2>
<ul class="hl">
<li><strong>AI Quality</strong> - an AI evaluator's judgement of structure, clarity, specificity and reusability.</li>
<li><strong>AI Usefulness estimate</strong> - the evaluator's estimate of how useful the output is for its stated purpose.</li>
<li><strong>Evaluation Confidence</strong> - how confident the evaluation is, given prompt completeness and testing.</li>
<li><strong>Goal Match</strong> - computed per search: how well a prompt fits the goal you typed.</li>
<li><strong>Community results</strong> - real "worked / didn't work" votes from visitors. Until a prompt has votes it shows "No votes yet", with the sample size shown once votes exist.</li>
</ul>
<h2>Why AI estimates?</h2>
<p>New prompts have no usage history. An AI evaluation gives an honest first signal, and community votes refine it over time using a weighting that prevents a prompt with two votes from outranking one with five hundred.</p>
<h2>Limitations</h2>
<p>AI scores are estimates and can be wrong. Always review a prompt's output before relying on it, especially for financial, legal or real-estate use.</p>"""),

    "source-policy": ("Content and source policy",
                      "Where prompts come from, how sourcing is disclosed, and licensing.", """
<p>We disclose the origin of every prompt.</p>
<ul class="hl">
<li><strong>Editorial prompts</strong> read "Created by BestPromptFinder" and are not user-generated.</li>
<li><strong>Third-party prompts</strong> link to the original source and state the licence (e.g. MIT). We keep the attribution and licence with the prompt.</li>
<li><strong>Dataset / gallery prompts</strong> are labelled by their platform.</li>
</ul>
<h2>Accuracy and claims</h2>
<p>Prompts and AI-generated previews must not invent prices, availability, footfall, yields, returns, guarantees, scarcity or testimonials. Previews insert <code>[VERIFY: ...]</code> where information is missing rather than fabricating it.</p>
<h2>Takedown</h2>
<p>If a prompt infringes your rights or is mis-attributed, email <a href="mailto:support@bestpromptfinder.com">support@bestpromptfinder.com</a> and we will correct or remove it.</p>"""),

    "submit": ("Submit a prompt",
               "Guidelines for submitting a prompt to BestPromptFinder.", """
<p>We welcome high-quality, tested prompts. To be accepted, a prompt should:</p>
<ul class="hl">
<li>Solve a clear, specific job and state the inputs it needs.</li>
<li>Be original, or link to its source and licence if adapted.</li>
<li>Contain no fabricated facts, guarantees, scarcity or testimonial-farming instructions.</li>
<li>Avoid personal data and anything unlawful in your jurisdiction.</li>
</ul>
<p>Send submissions or corrections to <a href="mailto:support@bestpromptfinder.com">support@bestpromptfinder.com</a> with the prompt text, its intended purpose, and a source link if applicable. Submitting does not guarantee inclusion; accepted prompts are reviewed and scored before they go live.</p>"""),

    "privacy": ("Privacy Policy",
                "How BestPromptFinder collects, uses and protects your data, and your rights under India's DPDP Act.", """
<p class="meta">Last updated: 2026-09-20. Governed by the laws of India, including the Digital Personal Data Protection Act, 2023 (DPDP).</p>
<p>BestPromptFinder ("we") is the data fiduciary for personal data processed through this site. This policy explains what we collect, why, who processes it, how long we keep it, and the rights you have as a data principal.</p>
<h2>What we collect and why</h2>
<ul class="hl">
<li><strong>Account data</strong> - if you create an account: your email and a securely hashed password, to authenticate you and hold your saved library.</li>
<li><strong>Usage data</strong> - your searches, saved prompts and "worked / didn't work" votes, used to rank prompts and improve the service.</li>
<li><strong>Technical data</strong> - standard server logs (IP address, browser type, timestamps) for security, abuse prevention and reliability.</li>
</ul>
<h2>Are my searches sent to third-party AI models?</h2>
<p>Yes, for two features only. When you run a <strong>live preview</strong> or use <strong>"prefill from my goal"</strong>, the relevant prompt/goal text is sent to our AI model provider (Anthropic) to generate that result. It is processed to return your result and is not used by us to build a profile of you. Ordinary keyword searching does not send your query to an external model beyond what is needed to rank results.</p>
<h2>Service providers (processors)</h2>
<p>We share the minimum data needed with: our hosting/VPS provider (to run the site), and our AI model provider, Anthropic (to generate previews and prefill). We do not sell your personal data or share it for advertising. We never place personal data in URLs.</p>
<h2>Retention and deletion</h2>
<p>Account and library data are kept while your account is active. Server logs are retained for a limited operational period and then deleted or anonymised. Preview/prefill inputs are not retained by us beyond returning the result. You can ask us to delete your account and associated data at any time.</p>
<h2>Your rights (DPDP)</h2>
<p>You have the right to access, correct, and erase your personal data, to withdraw consent, and to grievance redressal. To exercise any right, or to reach our Grievance Officer, contact <a href="mailto:support@bestpromptfinder.com">support@bestpromptfinder.com</a>. We will respond within the timelines required by law.</p>
<h2>Children</h2>
<p>The service is not directed at children, and we do not knowingly process children's data without verifiable parental consent as required by law.</p>
<p class="meta">Contact / Grievance Officer: support@bestpromptfinder.com</p>"""),

    "terms": ("Terms of Use",
              "The terms governing your use of BestPromptFinder.", """
<p class="meta">Last updated: 2026-09-20. Governed by the laws of India; courts at [CITY], India have exclusive jurisdiction.</p>
<h2>Use of the service</h2>
<p>BestPromptFinder is provided free of charge, on an "as is" and "as available" basis, for lawful use. Prompts and AI-generated previews are provided for convenience and may contain errors or omissions - you are responsible for reviewing and verifying any output before you rely on it, publish it, or use it commercially.</p>
<h2>No professional advice</h2>
<p>Nothing on this site is financial, investment, legal, tax or other professional advice. Scores shown are AI evaluations and estimates, not guarantees of results. Do not rely on generated content for regulated decisions without independent verification.</p>
<h2>Acceptable use</h2>
<p>Do not use the service to break the law, infringe others' rights, generate false, misleading or defamatory claims, fabricate testimonials or credentials, or attempt to disrupt or reverse-engineer the service.</p>
<h2>Intellectual property &amp; third-party prompts</h2>
<p>Third-party prompts remain under their original licences, shown on each prompt page. You are responsible for complying with those licences when you reuse a prompt, especially commercially. Editorial prompts created by BestPromptFinder may be used for your own work.</p>
<h2>Limitation of liability</h2>
<p>To the maximum extent permitted by law, BestPromptFinder and its operators are not liable for any indirect, incidental or consequential losses, or for losses arising from your use of the service or its outputs.</p>
<h2>Changes</h2>
<p>We may update these terms; continued use after an update means you accept the revised terms. Questions: <a href="mailto:support@bestpromptfinder.com">support@bestpromptfinder.com</a>.</p>"""),
}


def info_page(slug: str):
    entry = INFO_PAGES.get(slug)
    if not entry:
        return None
    title, desc, body = entry
    return _info(title, slug, desc, body)

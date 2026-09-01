"""
Multi-stage prompt-evaluation pipeline.

Stages (per production design):
  1. Raw storage        -> keep original scraped text untouched (raw_prompt)
  2. Normalize          -> cleaned_prompt + extracted features
  3. Rule-based filter  -> drop obvious junk / low-effort (cheap, no LLM)
  4. Exact + near dedup -> hash + token-Jaccard, keep best canonical
  5. Type detection     -> text / image / coding / data / other
  6. Quality evaluation -> heuristic rubric now, LLM judge when a key is present
  7. Purpose classify   -> use-case taxonomy (separate from quality)
  8. Library value      -> is this worth keeping in a reusable library?
  9. Final ranking       -> quality*0.7 + library_value*0.3
 10. KEEP / REVIEW / DROP

The heuristic scorer mirrors the 6-component rubric with type-specific weights so
that, with or without an LLM key, every row gets a comparable 0-100 score.
"""
import os
import re
import math
import hashlib
import logging
from html import unescape
from typing import List, Dict, Any, Tuple

log = logging.getLogger("scraper_agent")

try:
    import llm_evaluator
except Exception:  # module optional
    llm_evaluator = None


# ==========================================
# STAGE 2 — NORMALIZATION
# ==========================================
_URL_RX = re.compile(r"https?://\S+")
_EMOJI_RX = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF←-⇿⬀-⯿]"
)
_PLACEHOLDER_RX = re.compile(r"(\{[A-Za-z0-9_ ]+\}|\[[A-Z0-9_ ]{2,}\]|<[A-Za-z0-9_ ]+>)")
_PARAM_RX = re.compile(r"--(ar|stylize|v|q|chaos|seed|niji|no|iw)\b|temperature\s*=|top_p\s*=", re.I)
_CODE_RX = re.compile(r"```|def |class |import |SELECT |function\s*\(|</?[a-z]+>", re.I)
_WORD_RX = re.compile(r"[A-Za-z0-9]+")
_STOPWORDS = {"the", "a", "an", "and", "or", "to", "of", "in", "for", "you", "your", "is",
              "with", "this", "that", "as", "on", "be", "are", "will", "it", "i", "me", "my"}


def normalize_prompt(raw: str) -> Tuple[str, Dict[str, Any]]:
    """Clean scraped text and extract structural features. Never mutates the raw copy."""
    text = unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", text)                 # strip stray HTML
    urls = _URL_RX.findall(text)
    text_no_url = _URL_RX.sub(" ", text)
    text_clean = re.sub(r"\s+", " ", text_no_url).strip()

    words = _WORD_RX.findall(text_clean)
    n_words = len(words)
    lower_words = [w.lower() for w in words]
    unique_ratio = (len(set(lower_words)) / n_words) if n_words else 0.0

    alpha = [c for c in text_clean if c.isalpha()]
    latin = [c for c in alpha if ord(c) < 128]
    latin_ratio = (len(latin) / len(alpha)) if alpha else 1.0

    features = {
        "word_count": n_words,
        "char_count": len(text_clean),
        "unique_ratio": round(unique_ratio, 3),
        "url_count": len(urls),
        "url_char_ratio": round(sum(len(u) for u in urls) / max(1, len(raw or "")), 3),
        "emoji_count": len(_EMOJI_RX.findall(text)),
        "has_placeholder": bool(_PLACEHOLDER_RX.search(text_clean)),
        "has_params": bool(_PARAM_RX.search(text_clean)),
        "has_code": bool(_CODE_RX.search(raw or "")),
        "repeated_run": bool(re.search(r"(.)\1{5,}", text_clean)),
        "latin_ratio": round(latin_ratio, 3),
        "has_stopword": any(w in _STOPWORDS for w in lower_words),
    }
    return text_clean, features


# ==========================================
# STAGE 5 — PROMPT TYPE
# ==========================================
_IMG_HINT = re.compile(
    r"--(ar|stylize|v|niji)\b|midjourney|dall-?e|stable diffusion|photoreal|hyper-?realistic|"
    r"cinematic|8k|4k|portrait|render|octane|concept art|illustration|bokeh|lens|golden hour", re.I)
_CODE_HINT = re.compile(
    r"\b(code|function|python|javascript|typescript|java|c\+\+|sql|regex|api|compile|debug|"
    r"refactor|terminal|console|algorithm|json|bug)\b", re.I)
_DATA_HINT = re.compile(
    r"\b(dataset|spreadsheet|csv|excel|analy[sz]e|statistic|chart|dataframe|pivot|sql query)\b", re.I)


def detect_type(text: str, category: str = "") -> str:
    hay = f"{category} {text}".lower()
    if _IMG_HINT.search(hay) or "image" in category.lower():
        return "image"
    if _DATA_HINT.search(hay):
        return "data"
    if _CODE_HINT.search(hay):
        return "coding"
    return "text"


# ==========================================
# STAGE 3 — RULE-BASED PRE-FILTER (cheap junk/low-effort rejects)
# ==========================================
def prefilter(text: str, features: Dict[str, Any], ptype: str) -> Tuple[bool, str]:
    n = features["word_count"]
    min_words = 8 if ptype == "image" else 15
    dense_ok = features["unique_ratio"] >= 0.6 and n >= 6   # short-but-dense escape hatch

    if n < min_words and not dense_ok:
        return False, "low-effort (too short / low density)"
    if features["url_char_ratio"] > 0.70:
        return False, "mostly URL"
    if features["repeated_run"] and features["unique_ratio"] < 0.35:
        return False, "repeated-character spam"
    if features["char_count"] and features["emoji_count"] / max(1, n) > 0.5:
        return False, "emoji spam"
    if features["char_count"] > 20000:
        return False, "oversized dump"
    # Garbled (mixed non-latin with no recognizable words) — but keep coherent non-English
    if features["latin_ratio"] < 0.5 and not features["has_stopword"] and features["unique_ratio"] < 0.5:
        return False, "garbled / unreadable"
    return True, ""


# ==========================================
# STAGE 7 — PURPOSE TAXONOMY (separate from quality)
# ==========================================
PURPOSE_TAXONOMY = {
    "Image Generation": ["--ar", "--stylize", "--niji", "midjourney", "dall-e", "stable diffusion",
                         "photoreal", "hyper-realistic", "cinematic", "concept art", "portrait",
                         "8k", "render", "octane", "illustration", "bokeh", "golden hour"],
    "Debugging": ["debug", "fix the bug", "stack trace", "error message", "why does this fail",
                  "not working", "traceback"],
    "Coding": ["code", "function", "python", "javascript", "typescript", "sql", "regex", "api",
               "refactor", "algorithm", "terminal", "console", "compile", "unit test"],
    "Data/Analysis": ["dataset", "spreadsheet", "csv", "excel", "analyze data", "statistic",
                      "chart", "dataframe", "pivot", "insight", "trend"],
    "SEO": ["seo", "search engine", "keyword research", "meta description", "backlink", "serp"],
    "Marketing": ["marketing", "ad copy", "advertis", "campaign", "brand", "landing page",
                  "email subject", "cta", "copywriting", "funnel"],
    "Sales": ["cold email", "cold outreach", "sales pitch", "prospect", "lead", "close the deal"],
    "Social Media": ["instagram", "tiktok", "twitter", "linkedin post", "facebook", "reels",
                     "hashtag", "social media"],
    "Translation": ["translate", "translation", "in spanish", "in french", "into english"],
    "Summarization": ["summarize", "summary", "tl;dr", "key points", "condense"],
    "Editing / Rewriting": ["rewrite", "paraphrase", "edit this", "proofread", "improve the",
                            "make it more", "grammar"],
    "Research": ["research", "literature review", "find sources", "cite", "investigate", "compare studies"],
    "Finance": ["invoice", "budget", "financial", "roi", "revenue", "profit", "tax", "accounting"],
    "Legal": ["contract", "legal", "terms and conditions", "nda", "clause", "compliance", "gdpr"],
    "Real Estate": ["real estate", "property", "home buyer", "listing", "mortgage", "rent"],
    "Ecommerce": ["product description", "shopify", "amazon listing", "ecommerce", "checkout"],
    "Customer Support": ["customer support", "support ticket", "refund", "help desk", "complaint"],
    "Career / Jobs": ["resume", "cover letter", "job interview", "cv ", "linkedin profile", "career"],
    "Education": ["explain", "teach", "tutor", "lesson", "study", "quiz", "beginner", "step by step"],
    "Business": ["business plan", "strategy", "pitch deck", "proposal", "swot", "roadmap", "stakeholder"],
    "Roleplay": ["act as", "you are a", "pretend", "roleplay", "character", "persona", "simulate"],
    "Brainstorming": ["brainstorm", "ideas for", "generate ideas", "list of ideas"],
    "Planning": ["plan a", "itinerary", "schedule", "timeline", "roadmap"],
    "Productivity": ["checklist", "organize", "workflow", "prioritize", "todo", "automate my"],
    "Automation": ["zapier", "automation", "webhook", "integrate", "no-code"],
    "Prompt Engineering": ["prompt engineering", "system prompt", "jailbreak", "prompt template"],
    "Writing": ["write", "essay", "story", "blog", "article", "poem", "script", "screenplay"],
}


def classify_purpose(text: str, category: str = "") -> str:
    hay = f"{category} {text}".lower()
    for purpose, kws in PURPOSE_TAXONOMY.items():
        if any(kw in hay for kw in kws):
            return purpose
    return ""


# ==========================================
# STAGE 6 — HEURISTIC RUBRIC (type-weighted, mirrors LLM rubric)
# ==========================================
# Component weights by type (positives sum to 90; junk penalty is separate 0..-20).
RUBRIC_WEIGHTS = {
    "text":   {"length": 10, "instruction": 20, "output": 20, "specificity": 25, "context": 15},
    "coding": {"length": 10, "instruction": 18, "output": 18, "specificity": 29, "context": 15},
    "data":   {"length": 10, "instruction": 18, "output": 18, "specificity": 29, "context": 15},
    "image":  {"length": 20, "instruction": 10, "output": 10, "specificity": 40, "context": 10},
}

_INSTR_STRONG = re.compile(r"\b(you are|act as|your task is|your job is|imagine you are)\b", re.I)
_INSTR_VERB = re.compile(
    r"\b(create|generate|write|analyz|compare|rewrite|explain|summariz|classif|extract|"
    r"calculate|design|evaluate|build|translate|describe|list|produce|draft)\b", re.I)
_FORMAT_RX = re.compile(
    r"\b(step[- ]by[- ]step|numbered|bullet|table|json|markdown|csv|\d+\s*(ideas|options|words|"
    r"posts|examples|bullet)|in the style of|tone|format|section|schema|only the|word[- ]count)\b", re.I)
_CONSTRAINT_RX = re.compile(
    r"(--\w+|\{[^}]+\}|\[[A-Z0-9_ ]{2,}\]|\bexactly \d+|\bunder \d+|\bno more than|\bdo not\b|"
    r"\baudience\b|\btone\b|\bbudget\b|\bdeadline\b|\bformat\b|\bwithin \d+)", re.I)
_CONTEXT_RX = re.compile(
    r"\b(target audience|for (beginners|investors|students|developers)|background|context|"
    r"our company|the following|based on|assume|success criteria|platform|use case)\b", re.I)
_PERSONAL_RX = re.compile(
    r"\b(my wife|my husband|my mom|my dad|my boss|remind me|text my|my girlfriend|my boyfriend|"
    r"i'll be home|pick me up)\b", re.I)


def _frac_length(features, ptype):
    n = features["word_count"]
    dens = features["unique_ratio"]
    if n < (8 if ptype == "image" else 12):
        return 0.3 if dens >= 0.6 else 0.15
    if n > 800:
        return 0.5                       # long; penalize unless dense (approximated)
    base = 0.7
    if dens >= 0.55:
        base += 0.3
    return min(1.0, base)


def _frac_instruction(text, ptype):
    if ptype == "image":
        # Descriptive prompts rarely say "you are"; give partial baseline credit.
        return 0.6 if _INSTR_VERB.search(text) else 0.4
    if _INSTR_STRONG.search(text):
        return 1.0
    if _INSTR_VERB.search(text):
        return 0.7
    return 0.2


def _frac_output(text, ptype):
    if _FORMAT_RX.search(text):
        return 1.0
    if ptype == "image":
        return 0.6                       # the deliverable (an image) is implicit but clear
    return 0.3 if _INSTR_VERB.search(text) else 0.15


def _frac_specificity(text, features):
    hits = len(_CONSTRAINT_RX.findall(text))
    if features["has_params"]:
        hits += 2
    if features["has_placeholder"]:
        hits += 2
    return min(1.0, 0.1 + 0.18 * hits)


def _frac_context(text):
    if _CONTEXT_RX.search(text):
        return 0.9
    return 0.4


def _junk_penalty(features):
    pen = 0
    if features["url_char_ratio"] > 0.3:
        pen -= 12
    if features["emoji_count"] > 4:
        pen -= 6
    if features["repeated_run"]:
        pen -= 8
    if features["unique_ratio"] < 0.35:
        pen -= 8
    return max(-20, pen)


def heuristic_rubric(text: str, features: Dict[str, Any], ptype: str) -> Dict[str, Any]:
    w = RUBRIC_WEIGHTS.get(ptype, RUBRIC_WEIGHTS["text"])
    comp = {
        "length_score": round(_frac_length(features, ptype) * w["length"]),
        "instruction_score": round(_frac_instruction(text, ptype) * w["instruction"]),
        "output_score": round(_frac_output(text, ptype) * w["output"]),
        "specificity_score": round(_frac_specificity(text, features) * w["specificity"]),
        "context_score": round(_frac_context(text) * w["context"]),
    }
    junk = _junk_penalty(features)
    raw = sum(comp.values()) + junk
    quality = max(0, min(100, round(raw / 90 * 100)))
    comp["junk_penalty"] = junk
    comp["quality_score"] = quality
    return comp


# ==========================================
# STAGE 8 — LIBRARY VALUE
# ==========================================
def library_value(text: str, features: Dict[str, Any], purpose: str) -> int:
    v = 40
    if features["has_placeholder"]:
        v += 25                          # template-ready
    if features["has_params"]:
        v += 10
    if purpose and purpose != "Other":
        v += 10
    if _CONSTRAINT_RX.search(text):
        v += 10
    if _PERSONAL_RX.search(text):
        v -= 35                          # personal/ephemeral, not reusable
    if features["word_count"] < 6:
        v -= 15
    return max(0, min(100, v))


# ==========================================
# STAGE 10 — DECISION
# ==========================================
def decide(quality: int, keep_at: int, review_at: int) -> Tuple[str, str]:
    if quality >= keep_at:
        return "KEEP", tier_of(quality)
    if quality >= review_at:
        return "REVIEW", tier_of(quality)
    return "DROP", tier_of(quality)


def tier_of(score: int) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Strong"
    if score >= 60:
        return "Usable"
    if score >= 40:
        return "Weak"
    if score >= 20:
        return "Poor"
    return "Junk"


# ==========================================
# STAGE 4 — DEDUPLICATION
# ==========================================
def _dedup_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _shingles(text: str, k: int = 3) -> set:
    toks = _WORD_RX.findall(text.lower())
    if len(toks) < k:
        return {" ".join(toks)}
    return {" ".join(toks[i:i + k]) for i in range(len(toks) - k + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


# ==========================================
# ORCHESTRATION
# ==========================================
def evaluate_all(items: List[Any], keep_at: int = 70, review_at: int = 45,
                 use_llm: bool = None, model: str = None) -> List[Dict[str, Any]]:
    """Run the full pipeline over PromptData-like objects. Returns enriched row dicts
    for everything that survives pre-filter + dedup (decision column marks KEEP/REVIEW/DROP)."""
    rows: List[Dict[str, Any]] = []

    # Stages 1-3, 5, 7: normalize, type, prefilter, purpose
    dropped_prefilter = 0
    for it in items:
        raw = it.prompt_text or ""
        cleaned, feats = normalize_prompt(raw)
        ptype = detect_type(cleaned, it.category)
        ok, reason = prefilter(cleaned, feats, ptype)
        if not ok:
            dropped_prefilter += 1
            continue
        purpose = classify_purpose(cleaned, it.category)
        if not purpose:
            dropped_prefilter += 1
            continue  # hard-reject: no clear purpose
        rows.append({
            "_obj": it, "raw_prompt": raw, "cleaned_prompt": cleaned,
            "features": feats, "prompt_type": ptype, "purpose": purpose,
        })
    log.info("Pre-filter: %d dropped (low-effort/junk/no-purpose), %d survive.",
             dropped_prefilter, len(rows))

    # Cheap heuristic score now, so dedup can keep the best copy and the (expensive)
    # LLM only scores de-duplicated survivors.
    for r in rows:
        r["comp"] = heuristic_rubric(r["cleaned_prompt"], r["features"], r["prompt_type"])

    # Stage 4: exact dedup (keep the highest heuristic score among identical texts)
    best_by_key = {}
    for r in rows:
        key = _dedup_key(r["cleaned_prompt"])
        cur = best_by_key.get(key)
        if cur is None or r["comp"]["quality_score"] > cur["comp"]["quality_score"]:
            best_by_key[key] = r
    deduped = list(best_by_key.values())
    exact_removed = len(rows) - len(deduped)

    # Stage 4b: semantic near-dup (embeddings cosine >= threshold), canonical = best score
    import semantic
    sem_threshold = float(os.getenv("SEMANTIC_THRESHOLD", "0.92"))

    def _canon_score(r):
        return r["comp"]["quality_score"] + min(10.0, math.log1p(getattr(r["_obj"], "engagement", 0) or 0))

    kept_rows, near_removed = semantic.semantic_dedup(
        deduped,
        text_of=lambda r: r["cleaned_prompt"],
        score_of=_canon_score,
        purpose_of=lambda r: r["purpose"],
        threshold=sem_threshold,
    )
    log.info("Dedup: removed %d exact + %d semantic near-duplicate (%s, thr=%.2f); %d unique remain.",
             exact_removed, near_removed, semantic.backend_name(), sem_threshold, len(kept_rows))

    # Stage 6: quality — LLM judge when available, else heuristic
    if use_llm is None:
        use_llm = bool(llm_evaluator and llm_evaluator.available())
    llm_scores = {}
    if use_llm:
        resolved = model or os.getenv("LLM_MODEL", getattr(llm_evaluator, "DEFAULT_MODEL", "?"))
        # Optional cap: only send the top-N (by heuristic quality) to the LLM to bound cost.
        max_llm = int(os.getenv("LLM_MAX_ITEMS", "0"))
        order = sorted(range(len(kept_rows)), key=lambda i: kept_rows[i]["comp"]["quality_score"], reverse=True)
        if max_llm > 0:
            order = order[:max_llm]
        log.info("LLM evaluator active (model=%s) over %d of %d prompts...", resolved, len(order), len(kept_rows))
        payload = [{"id": str(i), "prompt": kept_rows[i]["cleaned_prompt"]} for i in order]
        try:
            llm_scores = llm_evaluator.evaluate(payload, model=model)
        except Exception as e:
            log.warning("LLM evaluation failed (%s); falling back to heuristic.", e)
            use_llm = False

    # Stages 6-10 + 12: assemble rows (with template extraction)
    import templates
    for i, r in enumerate(kept_rows):
        it, feats = r["_obj"], r["features"]
        comp = r["comp"]
        purpose = r["purpose"]
        eval_source = "heuristic"

        lj = llm_scores.get(str(i)) if use_llm else None
        if lj and isinstance(lj.get("score"), (int, float)):
            comp["quality_score"] = int(lj["score"])
            b = lj.get("breakdown") or {}
            for k_src, k_dst in [("length_information_density", "length_score"),
                                 ("instruction_framing", "instruction_score"),
                                 ("output_format", "output_score"),
                                 ("specificity_constraints", "specificity_score"),
                                 ("context_completeness", "context_score"),
                                 ("junk_penalty", "junk_penalty")]:
                if k_src in b:
                    comp[k_dst] = b[k_src]
            purpose = lj.get("purpose") or purpose
            eval_source = "llm"

        quality = comp["quality_score"]
        libval = library_value(r["cleaned_prompt"], feats, purpose)
        final = round(quality * 0.7 + libval * 0.3)
        decision, tier = decide(quality, keep_at, review_at)
        if lj and lj.get("decision"):
            decision = lj["decision"]

        # Stage 12: reusable template + variables
        template_prompt, variables = templates.extract_template(r["cleaned_prompt"])
        is_template = templates.is_template_worthy(template_prompt, variables)

        rows_out_append = {
            "final_score": final,
            "quality_score": quality,
            "library_value": libval,
            "tier": tier,
            "decision": decision,
            "prompt_type": r["prompt_type"],
            "purpose": purpose,
            "platform": it.platform,
            "title": it.title,
            "cleaned_prompt": r["cleaned_prompt"],
            "template_prompt": template_prompt,
            "variables": ", ".join(variables),
            "is_template": is_template,
            "raw_prompt": r["raw_prompt"],
            "word_count": feats["word_count"],
            "language": "latin" if feats["latin_ratio"] >= 0.9 else "non-latin",
            "length_score": comp["length_score"],
            "instruction_score": comp["instruction_score"],
            "output_score": comp["output_score"],
            "specificity_score": comp["specificity_score"],
            "context_score": comp["context_score"],
            "junk_penalty": comp["junk_penalty"],
            "duplicate_status": "unique",
            "model_target": it.model_target,
            "category": it.category,
            "engagement": it.engagement,
            "eval_source": eval_source,
            "url": it.url,
        }
        r["out"] = rows_out_append

    return [r["out"] for r in kept_rows]

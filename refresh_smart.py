"""
Incremental library refresh — safe to run frequently (e.g. every few hours).

Unlike a full rebuild, this MERGES: it adds newly-scraped prompts (heuristic-graded) into
the existing corpus WITHOUT touching anything already there, then LLM-grades only the
still-ungraded prompts, bounded by the daily budget. So:
  * new prompts appear immediately (heuristic), even when the grading budget is spent
  * existing Claude grades are NEVER downgraded
  * grading simply catches up over subsequent runs as the daily budget allows

Run:  CORPUS_PATH=/data/corpus.json python refresh_smart.py
"""
import os
import json
import hashlib
import logging
from datetime import date, timedelta
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("refresh")

ROOT = os.path.dirname(os.path.abspath(__file__))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

import scraper_agent
import pipeline
import llm_evaluator
try:
    import budget
except Exception:
    budget = None

CORPUS = os.getenv("CORPUS_PATH", os.path.join(ROOT, "app", "backend", "corpus.json"))
MODELS = ["GPT-5.6", "Claude", "Gemini"]
MERGE_MIN_QUALITY = int(os.getenv("REFRESH_MIN_QUALITY", "45"))  # heuristic floor to admit a new scrape


def _h(s: str) -> int:
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


def seed_reliability(title: str, quality: int, engagement: int) -> Dict[str, Any]:
    h = _h(title)
    uses = 120 + (engagement or 0) * 4 + (h % 900)
    useful = max(78, min(96, 80 + quality // 8 + (h % 6)))
    tested = list(dict.fromkeys(MODELS[(h + i) % len(MODELS)] for i in range(1 + (h % 3))))
    verified = date.today() - timedelta(days=(h % 30))
    reliability = round(useful * 0.7 + min(100, uses / 12) * 0.3)
    return {"uses": uses, "useful": useful, "tested": tested,
            "last_verified": verified.isoformat(),
            "reliability": max(0, min(100, reliability)), "synthetic": True}


def load_corpus() -> List[Dict[str, Any]]:
    if os.path.exists(CORPUS):
        try:
            with open(CORPUS, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning("Could not read corpus (%s); starting empty.", e)
    return []


def save_corpus(corpus: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(CORPUS) or ".", exist_ok=True)
    tmp = CORPUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CORPUS)  # atomic — the API's mtime watcher reloads cleanly


def collect_new(corpus: List[Dict[str, Any]]) -> int:
    """Scrape all sources; append NEW (deduped) prompts with heuristic grades. No downgrades."""
    existing = {pipeline._dedup_key(c.get("prompt", "")) for c in corpus}
    used_ids = {c.get("id") for c in corpus}
    try:
        items = scraper_agent.scrape_all()
    except Exception as e:
        log.warning("Scrape failed (%s); skipping collect this run.", e)
        return 0
    added = 0
    for it in items:
        cleaned, feats = pipeline.normalize_prompt(getattr(it, "prompt_text", "") or "")
        if not cleaned:
            continue
        cat = getattr(it, "category", "") or ""
        ptype = pipeline.detect_type(cleaned, cat)
        ok, _why = pipeline.prefilter(cleaned, feats, ptype)
        if not ok:
            continue
        key = pipeline._dedup_key(cleaned)
        if key in existing:
            continue
        comp = pipeline.heuristic_rubric(cleaned, feats, ptype)
        quality = comp["quality_score"]
        if quality < MERGE_MIN_QUALITY:
            continue
        existing.add(key)
        title = (getattr(it, "title", "") or cleaned[:60]).strip()[:80]
        eng = int(getattr(it, "engagement", 0) or 0)
        purpose = pipeline.classify_purpose(cleaned, cat) or "Other"
        model = getattr(it, "model_target", "") or "Any"
        platform = getattr(it, "platform", "Scraped") or "Scraped"
        rel = seed_reliability(title, quality, eng)
        # Content-derived id: unique per prompt (prompts are deduped) and stable across runs.
        pid = "p_" + hashlib.md5(cleaned.encode("utf-8")).hexdigest()[:12]
        n = 0
        while pid in used_ids:                      # astronomically rare; keep it deterministic
            n += 1
            pid = "p_" + hashlib.md5((cleaned + "#" + str(n)).encode("utf-8")).hexdigest()[:12]
        used_ids.add(pid)
        corpus.append({
            "id": pid,
            "title": title, "prompt": cleaned, "template": cleaned, "variables": [],
            "is_template": bool(feats.get("has_placeholder")), "prompt_type": ptype, "purpose": purpose,
            "quality": quality, "library_value": pipeline.library_value(cleaned, feats, purpose),
            "platform": platform, "models": [model] if model and model != "Any" else rel["tested"],
            "reliability": rel,
            "provenance": {"source": platform, "url": getattr(it, "url", "") or "",
                           "collected": date.today().strftime("%Y-%m"), "version": "1.0",
                           "eval_source": "heuristic"},
            "engagement": eng,
        })
        added += 1
    log.info("Collected %d new prompts.", added)
    return added


def grade_ungraded(corpus: List[Dict[str, Any]]) -> int:
    """LLM-grade prompts still on heuristic scores, bounded by the daily budget."""
    if not llm_evaluator.available():
        log.info("LLM unavailable — skipping grading (prompts keep heuristic scores).")
        return 0
    if budget and not budget.allowed():
        log.info("Daily budget spent ($%.2f) — grading resumes when it resets.", budget.spent_today())
        return 0
    targets = [c for c in corpus if c.get("provenance", {}).get("eval_source") not in ("llm", "curated")]
    if not targets:
        log.info("Nothing to grade — everything is already AI-graded.")
        return 0
    prompts = [{"id": c["id"], "prompt": (c.get("prompt") or "")[:8000]} for c in targets]
    log.info("Grading %d prompts (budget remaining $%.2f)...", len(prompts),
             budget.remaining() if budget else -1.0)
    results = llm_evaluator.evaluate(prompts)
    by_id = {c["id"]: c for c in corpus}
    updated = 0
    for pid, r in results.items():
        c = by_id.get(pid)
        if not c or not isinstance(r, dict):
            continue
        if isinstance(r.get("score"), (int, float)):
            c["quality"] = int(r["score"])
        if r.get("purpose"):
            c["purpose"] = r["purpose"]
        if r.get("prompt_type"):
            c["prompt_type"] = r["prompt_type"]
        c.setdefault("provenance", {})["eval_source"] = "llm"
        c["eval_tier"] = r.get("tier")
        c["eval_decision"] = r.get("decision")
        updated += 1
    log.info("Graded %d prompts. Spent today: $%.2f", updated, budget.spent_today() if budget else -1.0)
    return updated


def dedupe_ids(corpus: List[Dict[str, Any]]) -> int:
    """Ensure every prompt has a unique id (repairs pre-existing collisions in place).
    First occurrence keeps its id; later collisions get a stable content-derived id."""
    seen: set = set()
    fixed = 0
    for c in corpus:
        pid = c.get("id")
        if pid and pid not in seen:
            seen.add(pid)
            continue
        cleaned = c.get("prompt", "")
        new = "p_" + hashlib.md5(cleaned.encode("utf-8")).hexdigest()[:12]
        n = 0
        while new in seen:
            n += 1
            new = "p_" + hashlib.md5((cleaned + "#" + str(n)).encode("utf-8")).hexdigest()[:12]
        c["id"] = new
        seen.add(new)
        fixed += 1
    if fixed:
        log.info("Repaired %d duplicate ids.", fixed)
    return fixed


def main():
    corpus = load_corpus()
    before = len(corpus)
    dedupe_ids(corpus)
    added = collect_new(corpus)
    if added:
        save_corpus(corpus)          # new prompts go live immediately, before the (slow) grading
    graded = grade_ungraded(corpus)
    corpus = [c for c in corpus if c.get("eval_decision") != "DROP"]  # drop LLM-rejected junk
    save_corpus(corpus)
    log.info("Refresh done. %d -> %d prompts (+%d new, %d graded).", before, len(corpus), added, graded)


if __name__ == "__main__":
    main()

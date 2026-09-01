"""
One-shot: AI-grade the current library in place, capped by the daily budget guard.

Loads corpus.json, sends every heuristic-graded prompt through the Batch LLM evaluator
(50% off, ~1h), and writes the real scores back (quality, purpose, tier, decision,
eval_source='llm'). Curated + already-LLM items are skipped. The daily $1 guard makes it
impossible to overspend; anything that doesn't fit keeps its heuristic score.

Run:  python grade_corpus_now.py
"""
import os
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("grade")

ROOT = os.path.dirname(os.path.abspath(__file__))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

import budget
import llm_evaluator

CORPUS = os.path.join(ROOT, "app", "backend", "corpus.json")
MAX_PROMPT_CHARS = 8000  # bound pathological outliers so one chunk can't blow the estimate


def main():
    if not llm_evaluator.available():
        raise SystemExit("LLM not available — check ANTHROPIC_API_KEY in .env")

    with open(CORPUS, "r", encoding="utf-8") as f:
        corpus = json.load(f)

    targets = [c for c in corpus if c.get("provenance", {}).get("eval_source") not in ("llm", "curated")]
    log.info("Corpus=%d  to-grade=%d  budget remaining=$%.2f (cap $%.2f)",
             len(corpus), len(targets), budget.remaining(), budget.cap())
    if not targets:
        log.info("Nothing to grade."); return

    prompts = [{"id": c["id"], "prompt": (c.get("prompt") or "")[:MAX_PROMPT_CHARS]} for c in targets]

    log.info("Submitting to Batch evaluator (this polls ~1h)...")
    results = llm_evaluator.evaluate(prompts)   # batch by default (LLM_USE_BATCH=1)
    log.info("Evaluator returned %d scored prompts. Spent today so far: $%.2f",
             len(results), budget.spent_today())

    if not results:
        log.warning("No results returned — corpus unchanged."); return

    by_id = {c["id"]: c for c in corpus}
    updated = 0
    dec_counts = {"KEEP": 0, "REVIEW": 0, "DROP": 0}
    for pid, r in results.items():
        c = by_id.get(pid)
        if not c or not isinstance(r, dict):
            continue
        score = r.get("score")
        if isinstance(score, (int, float)):
            c["quality"] = int(score)
        if r.get("purpose"):
            c["purpose"] = r["purpose"]
        if r.get("prompt_type"):
            c["prompt_type"] = r["prompt_type"]
        c.setdefault("provenance", {})["eval_source"] = "llm"
        c["eval_tier"] = r.get("tier")
        c["eval_decision"] = r.get("decision")
        dec_counts[r.get("decision", "")] = dec_counts.get(r.get("decision", ""), 0) + 1
        updated += 1

    # Default: drop prompts the LLM judged junk (decision == "DROP"). Set REMOVE_DROP=0
    # to keep them (they'd just rank last). This keeps the served library high-quality.
    remove_drop = os.getenv("REMOVE_DROP", "1") != "0"
    before = len(corpus)
    if remove_drop:
        corpus = [c for c in corpus if c.get("eval_decision") != "DROP"]
    dropped = before - len(corpus)

    tmp = CORPUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CORPUS)

    log.info("DONE. Updated %d prompts. Decisions: %s. Removed %d DROP-verdict prompts. "
             "Corpus now %d. Total spent today: $%.2f",
             updated, dec_counts, dropped, len(corpus), budget.spent_today())


if __name__ == "__main__":
    main()

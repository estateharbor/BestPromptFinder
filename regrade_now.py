"""
One-off AI grading runs, using whichever provider llm_evaluator is configured for (Anthropic,
or the Emergent Universal Key via LLM_PROVIDER=emergent / EMERGENT_LLM_KEY).

Default: grade every prompt still on a heuristic score (e.g. new editorial rewrites).
REGRADE_ALL=1: re-grade every non-curated prompt that isn't on the current grading version
(llm_evaluator.GRADE_VERSION: one prompt per request + calibration anchors). Prompts keep
their existing score until the new grade lands, so nothing drops out of the sitemap mid-run,
and categories are left as they are.

Grades in slices and saves after each slice, so an interruption keeps finished work and a
re-run simply continues. Bounded by DAILY_BUDGET_USD like every other LLM call.

On the VPS:
  docker compose -f docker-compose.yml -f docker-compose.hostnginx.yml run --rm \
      -e LLM_PROVIDER=emergent -e DAILY_BUDGET_USD=3 pipeline python regrade_now.py
  # full consistent re-grade:
  docker compose ... run --rm -e LLM_PROVIDER=emergent -e REGRADE_ALL=1 -e DAILY_BUDGET_USD=15 \
      pipeline python regrade_now.py
"""
import os
import sys

os.environ.setdefault("CORPUS_PATH", "/data/corpus.json")
import refresh_smart  # noqa: E402  (reads CORPUS_PATH at import)
import llm_evaluator  # noqa: E402
import budget  # noqa: E402

SLICE = int(os.getenv("REGRADE_SLICE", "150"))
REGRADE_ALL = os.getenv("REGRADE_ALL") == "1"
log = refresh_smart.log


def _needs_regrade(c):
    if (c.get("provenance") or {}).get("eval_source") == "curated":
        return False
    return c.get("grade_version") != llm_evaluator.GRADE_VERSION


def _regrade_slice(items):
    """Grade items in place (score, tier, decision, type; NOT purpose). Returns (count, status)."""
    if budget and not budget.allowed():
        return 0, "budget_exhausted"
    prompts = [{"id": c["id"], "prompt": (c.get("prompt") or "")[:8000]} for c in items]
    try:
        results = llm_evaluator.evaluate(prompts)
    except Exception as e:
        log.warning("Grading unavailable (%s).", e)
        return 0, "error"
    by_id = {c["id"]: c for c in items}
    n = 0
    for pid, r in results.items():
        c = by_id.get(pid)
        if not c or not isinstance(r, dict) or not isinstance(r.get("score"), (int, float)):
            continue
        c["quality"] = int(r["score"])
        if r.get("prompt_type"):
            c["prompt_type"] = r["prompt_type"]
        c["eval_tier"], c["eval_decision"] = r.get("tier"), r.get("decision")
        c["grade_version"] = r.get("grade_version") or llm_evaluator.GRADE_VERSION
        c.setdefault("provenance", {})["eval_source"] = "llm"
        n += 1
    return n, "ok"


def main():
    if not llm_evaluator.available():
        sys.exit(f"No LLM credential for provider '{llm_evaluator.provider()}'. "
                 "Set EMERGENT_LLM_KEY (or ANTHROPIC_API_KEY) in app/.env.")
    log.info("Provider: %s | mode: %s | budget cap $%.2f, spent today $%.2f",
             llm_evaluator.provider(), "re-grade all (v%d)" % llm_evaluator.GRADE_VERSION if REGRADE_ALL else "ungraded only",
             budget.cap(), budget.spent_today())
    total = 0
    while True:
        corpus = refresh_smart.load_corpus()
        if REGRADE_ALL:
            todo = [c for c in corpus if _needs_regrade(c)]
        else:
            todo = [c for c in corpus if (c.get("provenance") or {}).get("eval_source") not in ("llm", "curated")]
        if not todo:
            log.info("Nothing left to grade.")
            break
        log.info("%d prompts still to grade; grading the next %d...", len(todo), min(SLICE, len(todo)))
        if REGRADE_ALL:
            graded, status = _regrade_slice(todo[:SLICE])
        else:
            graded, status = refresh_smart.grade_ungraded(todo[:SLICE])  # mutates the shared dicts
        if graded:
            refresh_smart.save_corpus(corpus)
            total += graded
        if status != "ok" or graded == 0:
            log.warning("Stopping (status=%s). Re-run later to continue.", status)
            break
    log.info("Done this run: %d prompts graded. Spent today: $%.2f", total, budget.spent_today())


if __name__ == "__main__":
    main()

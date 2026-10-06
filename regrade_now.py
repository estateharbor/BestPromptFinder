"""
One-off: AI-grade every prompt still on a heuristic score (e.g. the audit's editorial
rewrites), using whichever provider llm_evaluator is configured for (Anthropic, or the
Emergent Universal Key via LLM_PROVIDER=emergent / EMERGENT_LLM_KEY).

Grades in slices and saves after each slice, so an interruption keeps finished work and a
re-run simply continues. Bounded by DAILY_BUDGET_USD like every other LLM call.

On the VPS:
  docker compose -f docker-compose.yml -f docker-compose.hostnginx.yml run --rm \
      -e DAILY_BUDGET_USD=3 pipeline python regrade_now.py
"""
import os
import sys

os.environ.setdefault("CORPUS_PATH", "/data/corpus.json")
import refresh_smart  # noqa: E402  (reads CORPUS_PATH at import)
import llm_evaluator  # noqa: E402
import budget  # noqa: E402

SLICE = int(os.getenv("REGRADE_SLICE", "150"))
log = refresh_smart.log


def main():
    if not llm_evaluator.available():
        sys.exit(f"No LLM credential for provider '{llm_evaluator.provider()}'. "
                 "Set EMERGENT_LLM_KEY (or ANTHROPIC_API_KEY) in app/.env.")
    log.info("Provider: %s | budget cap $%.2f, spent today $%.2f",
             llm_evaluator.provider(), budget.cap(), budget.spent_today())
    total = 0
    while True:
        corpus = refresh_smart.load_corpus()
        todo = [c for c in corpus if (c.get("provenance") or {}).get("eval_source") not in ("llm", "curated")]
        if not todo:
            log.info("Nothing left to grade.")
            break
        log.info("%d prompts still need grading; grading the next %d...", len(todo), min(SLICE, len(todo)))
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

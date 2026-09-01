#!/bin/sh
# Nightly refresh: collect new prompts -> clean/grade -> rebuild the served corpus.
# Writes to the shared /data volume that the API auto-reloads.
set -e

echo "[refresh] $(date -u) starting pipeline..."

# 1) Scrape all sources, clean, dedup, AI-grade (bounded by DAILY_BUDGET_USD) -> xlsx
OUTPUT_XLSX=/data/legal_ai_prompts.xlsx python scraper_agent.py

# 2) Turn the pipeline output into the searchable corpus the API serves
PIPELINE_XLSX=/data/legal_ai_prompts.xlsx CORPUS_PATH=/data/corpus.json \
    python backend/build_corpus.py

echo "[refresh] $(date -u) done. corpus written to /data/corpus.json"

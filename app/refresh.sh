#!/bin/sh
# Incremental refresh: add new prompts (heuristic, instant) + grade the ungraded within the
# daily budget. Merges into the served corpus — never downgrades existing Claude grades.
# Safe to run frequently (e.g. every few hours).
set -e
echo "[refresh] $(date -u) starting incremental refresh..."
CORPUS_PATH=/data/corpus.json python refresh_smart.py
echo "[refresh] $(date -u) done. corpus at /data/corpus.json"

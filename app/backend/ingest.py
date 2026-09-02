"""
Manual prompt ingestion — turn an Excel/CSV file you collected into live library entries.

Flow (all local, no LLM needed at upload time):
  read file -> map flexible columns -> normalize + prefilter (drop junk)
            -> heuristic quality/purpose/library-value grade
            -> dedup against the live corpus
            -> append to corpus.json (shows up immediately)
            -> append to sources/uploaded.json (nightly pipeline re-grades with the LLM)

So an upload is visible in seconds with heuristic scores, and gets a real AI grade
on the next nightly run — same "heuristic now, LLM later" pattern the scrapers use.
"""
import io
import os
import sys
import json
import hashlib
from datetime import date
from typing import Any, Dict, List

import pandas as pd

HERE = os.path.dirname(__file__)
# pipeline.py lives at the repo root (two levels up); make it importable.
_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pipeline
import build_corpus  # reuse seed_reliability() so uploaded entries match scraped ones

CORPUS = os.getenv("CORPUS_PATH", os.path.join(HERE, "corpus.json"))
UPLOADED = os.path.join(HERE, "sources", "uploaded.json")

# Flexible column mapping — accept whatever a human/AI-filled sheet calls things.
# First matching column (case-insensitive) wins.
_COLS = {
    "prompt":  ["prompt", "prompt_text", "text", "template", "body", "content"],
    "title":   ["title", "name", "prompt name", "headline"],
    "purpose": ["purpose", "use case", "use_case", "category", "job", "tag"],
    "model":   ["model", "model_target", "target model", "for", "tool"],
    "source":  ["source", "url", "link", "provenance", "origin"],
    "engagement": ["engagement", "upvotes", "likes", "votes", "stars", "score"],
    # Mark a prompt you've personally reviewed: it goes live at top quality and is
    # NEVER AI-graded (eval_source "curated" is excluded from grading).
    "curated": ["curated", "reviewed", "skip_grading", "skip grading", "pre_reviewed", "best"],
    "quality": ["quality", "rating", "my_score", "score_override"],
}

_TRUE = {"1", "true", "yes", "y", "curated", "reviewed", "best", "x", "✓"}


def _pick(row: Dict[str, Any], keys: List[str]) -> str:
    low = {str(k).strip().lower(): v for k, v in row.items()}
    for k in keys:
        if k in low and pd.notna(low[k]):
            return str(low[k]).strip()
    return ""


def _read_table(data: bytes, filename: str) -> pd.DataFrame:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return pd.read_csv(io.BytesIO(data))
    # default: Excel (.xlsx/.xls)
    return pd.read_excel(io.BytesIO(data))


def _existing_keys() -> set:
    """Normalized dedup keys already in the corpus, so re-uploads don't pile up."""
    keys = set()
    if os.path.exists(CORPUS):
        try:
            with open(CORPUS, "r", encoding="utf-8") as f:
                for c in json.load(f):
                    keys.add(pipeline._dedup_key(c.get("prompt", "")))
        except Exception:
            pass
    return keys


def _heuristic_entry(title: str, cleaned: str, feats: Dict[str, Any],
                     purpose_hint: str, model: str, source: str, engagement: int,
                     curated: bool = False, quality_override: int = None) -> Dict[str, Any]:
    ptype = pipeline.detect_type(cleaned, purpose_hint)
    # Trust an explicit purpose the uploader provided; only auto-classify when it's blank.
    purpose = purpose_hint.strip() if purpose_hint.strip() else (
        pipeline.classify_purpose(cleaned, "") or "Other")
    comp = pipeline.heuristic_rubric(cleaned, feats, ptype)
    quality = comp["quality_score"]
    libval = pipeline.library_value(cleaned, feats, purpose)
    if curated:
        # Reviewed by a human: trusted top-tier, never AI-graded.
        quality = quality_override if quality_override is not None else max(quality, 92)
        libval = max(libval, 90)
    eval_source = "curated" if curated else "heuristic"
    pid = "p_" + hashlib.md5((title + cleaned[:40]).encode()).hexdigest()[:10]
    rel = build_corpus.seed_reliability(title, quality, engagement)
    return {
        "id": pid, "title": title, "prompt": cleaned,
        "template": cleaned, "variables": [],
        "is_template": bool(feats.get("has_placeholder")),
        "prompt_type": ptype, "purpose": purpose,
        "quality": quality, "library_value": libval,
        "platform": "Uploaded", "models": [model] if model and model != "Any" else rel["tested"],
        "reliability": rel,
        "provenance": {"source": "Uploaded", "url": source, "collected": date.today().strftime("%Y-%m"),
                       "version": "1.0", "eval_source": eval_source},
        "engagement": engagement,
    }


def ingest_bytes(data: bytes, filename: str = "upload.xlsx",
                 keep_at: int = 45) -> Dict[str, Any]:
    """Parse an uploaded sheet and merge accepted prompts into the live library.

    Returns a summary: how many rows were read, added, skipped (dupes/junk), and why.
    """
    try:
        df = _read_table(data, filename)
    except Exception as e:
        raise ValueError(f"Could not read the file as Excel/CSV: {e}")

    if df.empty:
        return {"read": 0, "added": 0, "skipped": 0, "reasons": {}, "message": "The file had no rows."}

    rows = df.to_dict("records")
    existing = _existing_keys()
    seen_this_batch: set = set()

    new_entries: List[Dict[str, Any]] = []
    uploaded_records: List[Dict[str, Any]] = []
    reasons: Dict[str, int] = {}

    def _skip(reason: str):
        reasons[reason] = reasons.get(reason, 0) + 1

    for row in rows:
        raw = _pick(row, _COLS["prompt"])
        if not raw:
            _skip("no prompt text")
            continue
        cleaned, feats = pipeline.normalize_prompt(raw)
        ptype = pipeline.detect_type(cleaned, _pick(row, _COLS["purpose"]))
        curated = _pick(row, _COLS["curated"]).lower() in _TRUE
        if curated:
            # Human-reviewed: bypass the quality/length filter (trust it past the 20k cap),
            # but keep a sanity ceiling so a runaway paste can't wreck the corpus.
            if len(cleaned) > 60000:
                _skip("too large even for curated (>60k chars)")
                continue
        else:
            ok, why = pipeline.prefilter(cleaned, feats, ptype)
            if not ok:
                _skip(why)
                continue

        key = pipeline._dedup_key(cleaned)
        if key in existing or key in seen_this_batch:
            _skip("duplicate")
            continue
        seen_this_batch.add(key)

        title = (_pick(row, _COLS["title"]) or cleaned[:60]).strip()[:80]
        purpose_hint = _pick(row, _COLS["purpose"])
        model = _pick(row, _COLS["model"]) or "Any"
        source = _pick(row, _COLS["source"])
        eng_raw = _pick(row, _COLS["engagement"])
        try:
            engagement = int(float(eng_raw)) if eng_raw else 0
        except ValueError:
            engagement = 0

        q_raw = _pick(row, _COLS["quality"])
        try:
            quality_override = max(0, min(100, int(float(q_raw)))) if q_raw else None
        except ValueError:
            quality_override = None

        entry = _heuristic_entry(title, cleaned, feats, purpose_hint, model, source, engagement,
                                 curated=curated, quality_override=quality_override)

        if curated:
            # You've reviewed it: live immediately at top quality, never AI-graded, no bar.
            new_entries.append(entry)
            continue

        # Anything that survives prefilter + dedup is kept durably so the nightly LLM
        # re-grades it — the crude heuristic must never permanently lose a good prompt.
        uploaded_records.append({
            "title": title, "prompt": cleaned, "purpose": purpose_hint or entry["purpose"],
            "model": model, "source": source, "engagement": engagement,
        })
        # Only surface in the LIVE corpus now if it clears the heuristic bar; the rest
        # go live after the nightly LLM grade promotes them.
        if entry["quality"] < keep_at:
            _skip(f"queued for AI grading (heuristic {entry['quality']} < {keep_at})")
            continue
        new_entries.append(entry)

    if new_entries:
        _append_corpus(new_entries)
    if uploaded_records:
        _append_uploaded(uploaded_records)

    curated_live = sum(1 for e in new_entries if e["provenance"]["eval_source"] == "curated")
    non_curated_live = len(new_entries) - curated_live
    queued = len(uploaded_records) - non_curated_live   # kept for AI grade, not live yet
    junk = len(rows) - len(uploaded_records) - curated_live  # dropped (dupes / junk)
    curated_note = f"{curated_live} added as curated (reviewed, no AI grading); " if curated_live else ""
    return {
        "read": len(rows),
        "added": len(new_entries),
        "curated": curated_live,
        "queued_for_grading": queued,
        "skipped": junk,
        "reasons": reasons,
        "added_titles": [e["title"] for e in new_entries[:20]],
        "message": f"{len(new_entries)} of {len(rows)} prompts are live now; {curated_note}"
                   f"{queued} queued for AI grading; {junk} dropped (duplicates or junk).",
    }


def _append_corpus(entries: List[Dict[str, Any]]):
    corpus: List[Dict[str, Any]] = []
    if os.path.exists(CORPUS):
        try:
            with open(CORPUS, "r", encoding="utf-8") as f:
                corpus = json.load(f)
        except Exception:
            corpus = []
    corpus.extend(entries)
    tmp = CORPUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CORPUS)  # atomic — the API's mtime watcher reloads cleanly


def _append_uploaded(records: List[Dict[str, Any]]):
    """Durable store so the nightly scraper re-ingests + LLM-grades these prompts."""
    os.makedirs(os.path.dirname(UPLOADED), exist_ok=True)
    existing: List[Dict[str, Any]] = []
    if os.path.exists(UPLOADED):
        try:
            with open(UPLOADED, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing.extend(records)
    with open(UPLOADED, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

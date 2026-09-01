"""
Build the API corpus from the evaluation pipeline's output.

This is the wiring point: the pipeline (scrape -> normalize -> dedup -> quality ->
purpose -> templatize) produces `legal_ai_prompts.xlsx`; here we turn its KEEP/REVIEW
rows into `corpus.json` — the searchable, ranked prompt library the API serves.

Reliability fields (uses / useful% / tested models / last-verified) are *seeded*
deterministically per prompt for now; in production they come from real run telemetry
and "worked / didn't work" votes. They are marked clearly so nothing is passed off as
real usage data.
"""
import os
import json
import hashlib
from datetime import date, timedelta

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HERE = os.path.dirname(__file__)
# Configurable so the nightly job can read the freshly-produced xlsx from a shared
# volume and write corpus.json where the API auto-reloads it.
XLSX = os.getenv("PIPELINE_XLSX", os.path.join(ROOT, "legal_ai_prompts.xlsx"))
OUT = os.getenv("CORPUS_PATH", os.path.join(HERE, "corpus.json"))
SEED = os.path.join(HERE, "curated_seed.json")

MODELS = ["GPT-5.6", "Claude", "Gemini"]
# How many prompts to serve. Default high so the whole graded library is available;
# lower it (CORPUS_MAX_ITEMS) if you want a leaner corpus.
MAX_ITEMS = int(os.getenv("CORPUS_MAX_ITEMS", "5000"))


def _h(s: str) -> int:
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


def seed_reliability(title: str, quality: int, engagement: int):
    """Deterministic, clearly-synthetic reliability signals (placeholder for telemetry)."""
    h = _h(title)
    uses = 120 + (engagement or 0) * 4 + (h % 900)
    useful = max(78, min(96, 80 + quality // 8 + (h % 6)))
    n_models = 1 + (h % 3)
    tested = [MODELS[(h + i) % len(MODELS)] for i in range(n_models)]
    tested = list(dict.fromkeys(tested))  # dedupe, keep order
    verified = date.today() - timedelta(days=(h % 30))
    reliability = round(useful * 0.7 + min(100, uses / 12) * 0.3)
    return {
        "uses": uses,
        "useful": useful,
        "tested": tested,
        "last_verified": verified.isoformat(),
        "reliability": max(0, min(100, reliability)),
        "synthetic": True,
    }


def build():
    if not os.path.exists(XLSX):
        raise SystemExit(f"Pipeline output not found: {XLSX}\nRun the pipeline first (python scraper_agent.py).")
    df = pd.read_excel(XLSX)
    # KEEP/REVIEW already; rank by quality then take the strongest slice.
    if "quality_score" in df.columns:
        df = df.sort_values("quality_score", ascending=False)
    df = df.head(MAX_ITEMS).reset_index(drop=True)

    corpus = []

    # Curated seed pack — real, high-quality prompts that give the recommender strong
    # coverage of common professional jobs alongside the scraped corpus.
    if os.path.exists(SEED):
        with open(SEED, "r", encoding="utf-8") as f:
            for s in json.load(f):
                title, cleaned = s["title"], s["prompt"]
                pid = "p_" + hashlib.md5((title + cleaned[:40]).encode()).hexdigest()[:10]
                rel = seed_reliability(title, s.get("quality", 90), 400)
                corpus.append({
                    "id": pid, "title": title, "prompt": cleaned,
                    "template": s.get("template", cleaned), "variables": s.get("variables", []),
                    "is_template": bool(s.get("is_template")), "prompt_type": s.get("prompt_type", "text"),
                    "purpose": s.get("purpose", "Other"), "quality": s.get("quality", 90),
                    "library_value": 90, "platform": "Curated", "models": rel["tested"],
                    "reliability": rel,
                    "provenance": {"source": "Curated", "url": "", "collected": "2026-08",
                                   "version": "1.0", "eval_source": "curated"},
                    "engagement": 400,
                })
        print(f"Merged {len(corpus)} curated seed prompts.")

    for _, r in df.iterrows():
        title = str(r.get("title") or "Untitled").strip()
        cleaned = str(r.get("cleaned_prompt") or "").strip()
        if not cleaned:
            continue
        quality = int(r.get("quality_score") or 0)
        engagement = int(r.get("engagement") or 0) if pd.notna(r.get("engagement")) else 0
        pid = "p_" + hashlib.md5((title + cleaned[:40]).encode()).hexdigest()[:10]
        rel = seed_reliability(title, quality, engagement)
        variables = str(r.get("variables") or "")
        variables = [v.strip() for v in variables.split(",") if v.strip()]
        corpus.append({
            "id": pid,
            "title": title,
            "prompt": cleaned,
            "template": str(r.get("template_prompt") or cleaned),
            "variables": variables,
            "is_template": bool(r.get("is_template")),
            "prompt_type": str(r.get("prompt_type") or "text"),
            "purpose": str(r.get("purpose") or "Other"),
            "quality": quality,
            "library_value": int(r.get("library_value") or 0) if pd.notna(r.get("library_value")) else 0,
            "platform": str(r.get("platform") or "Unknown"),
            "models": rel["tested"],
            "reliability": rel,
            "provenance": {
                "source": str(r.get("platform") or "Unknown"),
                "url": str(r.get("url") or ""),
                "collected": "2026-08",
                "version": "1.0",
                "eval_source": str(r.get("eval_source") or "heuristic"),
            },
            "engagement": engagement,
        })

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(corpus)} prompts to {OUT}")


if __name__ == "__main__":
    build()

"""
Corpus remediation — flag (and optionally remove) unsafe or low-quality prompts.

Targets the audit's issues #4 and #8:
  - testimonial/success-story prompts that ask the model to INVENT customer results
  - junk / generic single-word titles (e.g. "Generation", "Prompt", "Untitled")
  - the low-quality tail (quality below a threshold)

SAFE BY DEFAULT: this is a DRY RUN unless you pass APPLY=1. It never touches curated
(human-reviewed) entries. When applied it writes a timestamped .bak first, then rewrites
CORPUS_PATH in place (add-only refresh won't resurrect these unless a scraper re-adds them).

Usage (on the VPS, inside the backend container):
  # review what would be removed:
  docker compose ... exec -T backend python remediate_corpus.py
  # actually remove, keeping a backup:
  docker compose ... exec -T backend sh -c "APPLY=1 python remediate_corpus.py"

Env:
  CORPUS_PATH   (default corpus.json)   the corpus to clean
  MIN_QUALITY   (default 40)            remove non-curated prompts below this
  APPLY         (default unset)         set to 1 to actually write changes
"""
import os
import re
import sys
import json
import shutil
from datetime import datetime

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    import pipeline
except Exception:
    pipeline = None

# Safe replacement for testimonial/success-story prompts (evidence-required, no fabrication).
SAFE_TESTIMONIAL = (
    "Using only the verified customer evidence supplied below, create 3-5 concise success "
    "stories. Do not invent customers, quotations, results, statistics or experiences. If "
    "evidence is missing, identify what information is required rather than generating a "
    "testimonial.\n\nVERIFIED CUSTOMER EVIDENCE:\n[paste verified evidence here]"
)

try:  # make console output safe for non-ASCII titles on any platform
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CORPUS = os.getenv("CORPUS_PATH", os.path.join(os.path.dirname(__file__), "corpus.json"))
MIN_QUALITY = int(os.getenv("MIN_QUALITY", "40"))
APPLY = os.getenv("APPLY") == "1"

# Titles that carry no information on their own.
JUNK_TITLES = {"generation", "prompt", "prompts", "untitled", "output", "result",
               "test", "example", "text", "image", "chat", "assistant", "ai", "gpt"}

# A prompt that asks the model to fabricate testimonials / success stories / reviews.
_TESTIMONIAL = re.compile(
    r"(testimonial|success stor|customer review|case study)", re.I)
_INVENTS = re.compile(
    r"\b(write|create|generate|make|produce|invent|come up with|craft)\b", re.I)
# ...but keep ones that explicitly require real/verified evidence (safe by construction).
_SAFE_GUARD = re.compile(
    r"(only.*(verified|supplied|real)|never invent|do not (invent|fabricate)|verified customer)", re.I)


def is_curated(c):
    return (c.get("provenance") or {}).get("eval_source") == "curated"


def _unsafe_testimonial(prompt):
    if pipeline is not None:
        return pipeline.is_unsafe_content(prompt)
    return bool(_TESTIMONIAL.search(prompt) and _INVENTS.search(prompt) and not _SAFE_GUARD.search(prompt))


def reason_to_drop(c):
    title = (c.get("title") or "").strip().lower()
    prompt = c.get("prompt") or ""
    if is_curated(c):
        return None  # never auto-remove human-reviewed prompts
    if title in JUNK_TITLES or len(title) < 4:
        return "junk/generic title"
    q = c.get("quality")
    if isinstance(q, (int, float)) and q < MIN_QUALITY:
        return f"low quality (<{MIN_QUALITY})"
    return None


def main():
    with open(CORPUS, "r", encoding="utf-8") as f:
        corpus = json.load(f)

    keep, drop, rewrite = [], [], []
    for c in corpus:
        # Testimonial-farming prompts are REWRITTEN to a safe, evidence-required version
        # (kept, not deleted) — even curated ones get made safe.
        if _unsafe_testimonial(c.get("prompt") or ""):
            rewrite.append(c)
            keep.append((c, None))
            continue
        r = reason_to_drop(c)
        (drop if r else keep).append((c, r))

    by_reason = {}
    for c, r in drop:
        by_reason.setdefault(r, []).append(c)

    print(f"Corpus: {len(corpus)} | keep: {len(keep)} | remove: {len(drop)} | rewrite (testimonial->safe): {len(rewrite)}  (MIN_QUALITY={MIN_QUALITY})")
    for reason, items in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        print(f"\n=== REMOVE — {reason}: {len(items)} ===")
        for c in items[:15]:
            print(f"  [{c.get('quality')}] {c.get('id')}  {(c.get('title') or '')[:60]!r}")
        if len(items) > 15:
            print(f"  ... and {len(items) - 15} more")
    if rewrite:
        print(f"\n=== REWRITE to evidence-required version: {len(rewrite)} ===")
        for c in rewrite[:15]:
            print(f"  {c.get('id')}  {(c.get('title') or '')[:60]!r}")

    if not APPLY:
        print("\nDRY RUN - nothing changed. Re-run with APPLY=1 to apply removals + rewrites.")
        return

    bak = f"{CORPUS}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(CORPUS, bak)
    for c in rewrite:
        c["prompt"] = SAFE_TESTIMONIAL
        c["template"] = SAFE_TESTIMONIAL
        c["variables"] = []
        c["is_template"] = False
    kept = [c for c, _ in keep]
    tmp = CORPUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CORPUS)
    print(f"\nAPPLIED: removed {len(drop)}, rewrote {len(rewrite)}. Backup at {bak}. New size: {len(kept)}.")
    print("The backend's mtime watcher will reload automatically.")


if __name__ == "__main__":
    main()

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


def reason_to_drop(c):
    title = (c.get("title") or "").strip().lower()
    prompt = c.get("prompt") or ""
    if is_curated(c):
        return None  # never auto-remove human-reviewed prompts
    if title in JUNK_TITLES or len(title) < 4:
        return "junk/generic title"
    if _TESTIMONIAL.search(prompt) and _INVENTS.search(prompt) and not _SAFE_GUARD.search(prompt):
        return "solicits invented testimonials/success stories"
    q = c.get("quality")
    if isinstance(q, (int, float)) and q < MIN_QUALITY:
        return f"low quality (<{MIN_QUALITY})"
    return None


def main():
    with open(CORPUS, "r", encoding="utf-8") as f:
        corpus = json.load(f)

    keep, drop = [], []
    for c in corpus:
        r = reason_to_drop(c)
        (drop if r else keep).append((c, r))

    by_reason = {}
    for c, r in drop:
        by_reason.setdefault(r, []).append(c)

    print(f"Corpus: {len(corpus)} | keep: {len(keep)} | flagged: {len(drop)}  (MIN_QUALITY={MIN_QUALITY})")
    for reason, items in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        print(f"\n=== {reason}: {len(items)} ===")
        for c in items[:15]:
            print(f"  [{c.get('quality')}] {c.get('id')}  {(c.get('title') or '')[:60]!r}")
        if len(items) > 15:
            print(f"  … and {len(items) - 15} more")

    if not APPLY:
        print("\nDRY RUN — nothing changed. Re-run with APPLY=1 to remove the flagged prompts.")
        return

    bak = f"{CORPUS}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(CORPUS, bak)
    kept = [c for c, _ in keep]
    tmp = CORPUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CORPUS)
    print(f"\nAPPLIED: removed {len(drop)} prompts. Backup at {bak}. New size: {len(kept)}.")
    print("The backend's mtime watcher will reload automatically.")


if __name__ == "__main__":
    main()

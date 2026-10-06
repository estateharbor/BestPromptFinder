"""
Apply a library audit to the corpus: remove, rewrite, or credit prompts by id.

Reads sources/audit/<audit>.csv (columns: id, decision, source, reasons, new_title, new_prompt,
licence) plus the optional sources/audit/manual_rewrites_<date>.json (second-pass rewrites by
id, and a "_remove" list). Decisions:
  remove   -> delete the prompt (its id is also in corpus_overrides.json "remove", and its text
              fingerprint is in sources/blocked_keys.txt, so it can't come back)
  rewrite  -> replace title + text with the editorial rewrite; source becomes BestPromptFinder;
              eval_source -> "heuristic" so the grader re-scores the NEW text (noindex until then)
  licence  -> keep the text, append the licence to the source URL: "https://… (CC0-1.0, …)"
  keep     -> no change

SAFE BY DEFAULT: dry run unless APPLY=1. When applied it writes a timestamped .bak first and
replaces CORPUS_PATH atomically (the API reloads on mtime).

Usage (on the VPS):
  docker compose ... exec -T backend python apply_audit.py                 # dry run
  docker compose ... exec -T backend sh -c "APPLY=1 python apply_audit.py" # apply
Env: CORPUS_PATH (default corpus.json), AUDIT (default sources/audit/audit_2026-10-06.csv),
     MANUAL (default sources/audit/manual_rewrites_2026-10-06.json), APPLY.
"""
import csv
import json
import os
import shutil
import sys
from collections import Counter
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import pipeline  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CORPUS = os.getenv("CORPUS_PATH", os.path.join(HERE, "corpus.json"))
AUDIT = os.getenv("AUDIT", os.path.join(HERE, "sources", "audit", "audit_2026-10-06.csv"))
MANUAL = os.getenv("MANUAL", os.path.join(HERE, "sources", "audit", "manual_rewrites_2026-10-06.json"))
APPLY = os.getenv("APPLY") == "1"
TODAY = datetime.now().strftime("%Y-%m-%d")


def load_plan():
    csv.field_size_limit(10 ** 8)
    with open(AUDIT, encoding="utf-8") as f:
        plan = {r["id"]: r for r in csv.DictReader(f)}
    manual = {}
    if os.path.exists(MANUAL):
        with open(MANUAL, encoding="utf-8") as f:
            manual = json.load(f)
    for pid in manual.get("_remove", []):
        if pid in plan:
            plan[pid]["decision"] = "remove"
    return plan, manual


def rewrite(c, row, manual_entry):
    title = (manual_entry or {}).get("title") or row.get("new_title") or c.get("title")
    text = (manual_entry or {}).get("prompt") or row.get("new_prompt")
    if not text:
        return False
    prev = c.get("provenance") or {}
    c["title"] = title.strip()[:80]
    c["prompt"] = c["template"] = text.strip()
    c["variables"] = []
    c["is_template"] = "[" in text
    c["platform"] = "Editorial"
    c["provenance"] = {
        "source": "BestPromptFinder (editorial rewrite)", "url": "",
        "collected": prev.get("collected") or datetime.now().strftime("%Y-%m"),
        "version": "2.0", "eval_source": "heuristic", "rewritten": TODAY,
        "audit_note": "Rewritten from the idea of an unlicensed or restricted public prompt.",
    }
    return True


def credit(c, licence):
    prov = c.setdefault("provenance", {})
    url = (prov.get("url") or "").strip()
    if url.endswith(")"):
        return False  # licence already recorded
    prov["url"] = f"{url or 'https://huggingface.co/datasets/fka/prompts.chat'} ({licence})"
    return True


def main():
    plan, manual = load_plan()
    with open(CORPUS, encoding="utf-8") as f:
        corpus = json.load(f)
    stats, out, seen = Counter(), [], set()
    for c in corpus:
        pid = c.get("id")
        row = plan.get(pid)
        if not row:
            out.append(c)
            continue
        seen.add(pid)
        d = row["decision"]
        if d == "remove":
            stats["removed"] += 1
            continue
        if d == "rewrite":
            stats["rewritten" if rewrite(c, row, manual.get(pid)) else "rewrite_missing_text"] += 1
        elif d == "licence":
            stats["licence_recorded" if credit(c, row["licence"]) else "licence_already_set"] += 1
        else:
            stats["kept"] += 1
        out.append(c)
    stats["not_in_corpus"] = len(set(plan) - seen)
    leftovers = [(c["id"], why) for c in out for why in [pipeline.content_violation(c.get("prompt", ""), c.get("title", ""))] if why]
    print(f"{'APPLY' if APPLY else 'DRY RUN'} on {CORPUS}: {len(corpus)} -> {len(out)} prompts")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    print(f"  still breaking content policy after audit (hidden at load anyway): {len(leftovers)}")
    for pid, why in leftovers[:20]:
        print(f"    {pid}: {why}")
    if not APPLY:
        print("Dry run only. Re-run with APPLY=1 to write changes.")
        return
    bak = f"{CORPUS}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
    shutil.copy2(CORPUS, bak)
    tmp = CORPUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CORPUS)
    print(f"Written. Backup: {bak}")


if __name__ == "__main__":
    main()

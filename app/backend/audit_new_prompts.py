"""
Library audit helper — used by the prompt-audit skill (.claude/skills/prompt-audit/SKILL.md).

  python audit_new_prompts.py export [out.csv]
      Lists every prompt in CORPUS_PATH that no file in sources/audit/*.csv covers yet, with
      automatic flags and a suggested action. Writes CSV to out.csv, or to stdout when omitted
      (so it can be piped out of the VPS container).

  python audit_new_prompts.py check decisions.csv
      Validates a finished decisions file before it is applied: every rewrite must be English,
      pass the content policy, and share under 10% of its 5-word runs with the original.
      Exits 1 if anything fails.

Decision files use the apply_audit.py format:
  id, decision (remove|rewrite|licence|keep), source, reasons, new_title, new_prompt, licence
"""
import csv
import glob
import io
import json
import os
import re
import sys

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
AUDIT_DIR = os.path.join(HERE, "sources", "audit")
SITE = "https://bestpromptfinder.com"

_CJK = re.compile(r"[぀-ヿ一-鿿가-힯]")
_STOCK = re.compile(r"\b(delve|tapestry|unleash|elevate|seamless(ly)?|cutting[- ]edge|game[- ]changer|"
                    r"in today's (fast-paced|digital)|masterpiece|award[- ]winning|trending on artstation|"
                    r"8k|ultra[- ]?detailed|hyper[- ]?realistic|octane render)\b", re.I)
_LICENCE_SUFFIX = re.compile(r"\([^)]+\)\s*$")
_WORDS = re.compile(r"\w+")


def audited_ids():
    """Ids already decided: listed in any sources/audit/*.csv or unpublished via corpus_overrides."""
    ids = set()
    try:
        with open(os.path.join(HERE, "sources", "corpus_overrides.json"), encoding="utf-8") as f:
            ids |= set(json.load(f).get("remove") or [])
    except (OSError, ValueError):
        pass
    for path in glob.glob(os.path.join(AUDIT_DIR, "*.csv")):
        with open(path, encoding="utf-8") as f:
            ids |= {r["id"] for r in csv.DictReader(f) if r.get("id")}
    return ids


def flags_for(c, corpus_shingles):
    text, title = c.get("prompt") or "", c.get("title") or ""
    prov = c.get("provenance") or {}
    url = (prov.get("url") or "").strip()
    flags = []
    why = pipeline.content_violation(text, title)
    if why:
        flags.append("POLICY:" + why)
    editorial = not url.startswith("http")
    if not editorial and not _LICENCE_SUFFIX.search(url):
        flags.append("NO_LICENCE")
    if len(_CJK.findall(text + title)) > 10:
        flags.append("NON_ENGLISH")
    parts = [p.strip() for p in text.split(",")]
    if len(parts) >= 6 and sum(len(p.split()) <= 3 for p in parts) / len(parts) > 0.6:
        flags.append("KEYWORD_SOUP")
    if len(_STOCK.findall(text)) >= 2:
        flags.append("AI_STOCK_WORDS")
    if re.match(r"\s*below is an instruction", text, re.I) or "### Instruction" in text or title.strip().lower() in ("generation", "prompt", "untitled"):
        flags.append("JUNK_DATASET_ROW")
    if len(text.split()) < 12:
        flags.append("TOO_SHORT")
    sh = pipeline._shingles(text)
    for other_id, other in corpus_shingles:
        if other_id != c["id"] and sh and other and len(sh & other) / len(sh | other) >= 0.8:
            flags.append(f"NEAR_DUPLICATE:{other_id}")
            break
    return flags, editorial


def suggest(flags, editorial):
    if any(f.startswith(("POLICY:", "NEAR_DUPLICATE", "JUNK_DATASET_ROW")) for f in flags):
        return "remove"
    if "NO_LICENCE" in flags or "NON_ENGLISH" in flags or "KEYWORD_SOUP" in flags:
        return "rewrite"
    return "keep" if editorial or not flags else "review"


def export(out_path=None):
    with open(CORPUS, encoding="utf-8") as f:
        corpus = json.load(f)
    done = audited_ids()
    todo = [c for c in corpus if c.get("id") not in done]
    shingles = [(c["id"], pipeline._shingles(c.get("prompt") or "")) for c in corpus]
    buf = io.StringIO() if not out_path else open(out_path, "w", encoding="utf-8", newline="")
    w = csv.writer(buf)
    w.writerow(["id", "url", "title", "category", "source", "source_url", "flags", "suggested_action", "original_prompt"])
    for c in todo:
        flags, editorial = flags_for(c, shingles)
        prov = c.get("provenance") or {}
        w.writerow([c["id"], f"{SITE}/prompt/{c['id']}", c.get("title", ""), c.get("purpose", ""),
                    prov.get("source", ""), prov.get("url", ""), ";".join(flags), suggest(flags, editorial),
                    c.get("prompt", "")])
    if out_path:
        buf.close()
        print(f"{len(todo)} unaudited prompts (of {len(corpus)}) -> {out_path}", file=sys.stderr)
    else:
        sys.stdout.write(buf.getvalue())
        print(f"{len(todo)} unaudited prompts (of {len(corpus)})", file=sys.stderr)


def _overlap(a, b, n=5):
    a, b = _WORDS.findall(a.lower()), _WORDS.findall(b.lower())
    if len(b) < n:
        return 0.0
    grams = {tuple(a[i:i + n]) for i in range(len(a) - n + 1)}
    runs = [tuple(b[i:i + n]) for i in range(len(b) - n + 1)]
    return sum(g in grams for g in runs) / len(runs)


def check(decisions_path):
    with open(CORPUS, encoding="utf-8") as f:
        originals = {c["id"]: c.get("prompt") or "" for c in json.load(f)}
    with open(decisions_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    bad = 0
    for r in rows:
        if r.get("decision") not in ("remove", "rewrite", "licence", "keep"):
            print(f"{r.get('id')}: unknown decision {r.get('decision')!r}"); bad += 1; continue
        if r["decision"] == "licence" and not r.get("licence"):
            print(f"{r['id']}: licence decision without a licence"); bad += 1
        if r["decision"] != "rewrite":
            continue
        new, title = r.get("new_prompt") or "", r.get("new_title") or ""
        problems = []
        if len(new.split()) < 12:
            problems.append("rewrite too short")
        if _CJK.search(new + title):
            problems.append("rewrite not in English")
        why = pipeline.content_violation(new, title)
        if why:
            problems.append("rewrite breaks policy: " + why)
        ov = _overlap(originals.get(r["id"], ""), new)
        if ov >= 0.10:
            problems.append(f"{ov:.0%} of 5-word runs copied from the original")
        if problems:
            bad += 1
            print(f"{r['id']}: " + "; ".join(problems))
    print(f"{len(rows)} rows checked, {bad} problem(s).")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "export":
        export(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "check" and len(sys.argv) > 2:
        check(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(2)

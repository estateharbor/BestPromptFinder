"""
Benchmark Emergent models for the search re-rank (llm_enrich).

Lists the models the Emergent key can use, then sends each candidate the real re-rank request
(same system prompt, real library prompts) a few times and reports latency, valid-JSON rate,
and whether it picks the same best prompt as the reference model. Costs a few cents.

On the VPS:
  docker compose -f docker-compose.yml -f docker-compose.hostnginx.yml exec -T backend python model_bench.py
Optional: MODELS="model-a,model-b" to test specific names; RUNS=3.
"""
import json
import os
import re
import statistics
import sys
import time
import urllib.request

import emergent_client
import llm_enrich
from api import rec

REFERENCE = "claude-sonnet-5"
RUNS = int(os.getenv("RUNS", "3"))
# Whole-word hints ("mini" must not match "gemini"); image / preview / pro models are skipped.
FAST_RE = re.compile(r"(?<![a-z])(haiku|mini|nano|flash|lite|small|fast)(?![a-z])", re.I)
SKIP_RE = re.compile(r"image|audio|tts|embed|realtime|vision|preview|pro", re.I)
GUESSES = ["claude-haiku-4-5-20251001", "claude-haiku-4-5", "gpt-5-mini", "gpt-5-nano", "gpt-4.1-mini",
           "gpt-4o-mini", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
GOALS = ["write a follow-up email after a property viewing",
         "plan a 4-week content calendar for a bakery's instagram",
         "review my python code for security bugs"]


def list_models():
    req = urllib.request.Request(emergent_client.BASE_URL.rstrip("/") + "/models",
                                 headers={"Authorization": f"Bearer {os.getenv('EMERGENT_LLM_KEY', '')}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return sorted({m.get("id") for m in json.loads(r.read()).get("data", []) if m.get("id")})
    except Exception as e:
        print(f"(model list unavailable: {e}; testing common names instead)")
        return []


def shortlist(goal):
    r = rec()
    res = r.search(goal, k=6, use_llm=False)
    ids = [x["id"] for x in res["results"] + res.get("related", [])][:6]
    return [{"id": c["id"], "title": c["title"], "prompt": c["prompt"][:400]} for c in (r._by_id[i] for i in ids)]


def run(model, goal, cands):
    payload = json.dumps({"goal": goal, "candidates": cands}, ensure_ascii=False)
    t = time.time()
    text, usage = emergent_client.chat(model, llm_enrich.SYSTEM, payload, max_tokens=900, timeout=60)
    dt = time.time() - t
    s, e = text.find("["), text.rfind("]")
    parsed = json.loads(text[s:e + 1]) if s >= 0 else []
    scores = {str(o["id"]): int(o.get("match", 0)) for o in parsed if isinstance(o, dict) and "id" in o}
    top = max(scores, key=scores.get) if scores else None
    return dt, len(scores) == len(cands), top, usage


def main():
    if not emergent_client.available():
        sys.exit("EMERGENT_LLM_KEY is not set in this container.")
    available = list_models()
    if available:
        print(f"Models available to this key ({len(available)}): {', '.join(available)}\n")
    wanted = [m.strip() for m in os.getenv("MODELS", "").split(",") if m.strip()]
    if not wanted:
        pool = available or GUESSES
        fast = [m for m in pool if FAST_RE.search(m) and not SKIP_RE.search(m)]
        # prefer current GPT minis/nanos, then Claude Haiku, then Gemini flash; skip dated duplicates
        order = lambda m: (0 if m.startswith("gpt") else 1 if "haiku" in m else 2, m)
        wanted = sorted(fast, key=order)[:10]
    models = [REFERENCE] + [m for m in wanted if m != REFERENCE]
    cases = [(g, shortlist(g)) for g in GOALS]
    ref_top = {}
    print(f"{'model':38} {'median s':>8} {'valid':>6} {'same #1 as ref':>15} {'in/out tok':>11}")
    for m in models:
        times, valid, agree, toks, err = [], 0, 0, [], ""
        for goal, cands in cases:
            for i in range(RUNS):
                try:
                    dt, ok, top, usage = run(m, goal, cands)
                except Exception as e:
                    err = str(e)[:90]
                    break
                times.append(dt); valid += ok; toks.append((usage["input"], usage["output"]))
                if m == REFERENCE and i == 0:
                    ref_top[goal] = top
                elif m != REFERENCE and i == 0 and top == ref_top.get(goal):
                    agree += 1
            if err:
                break
        if err:
            print(f"{m:38} {'-':>8}  error: {err}")
            continue
        n = len(times)
        tin = int(statistics.mean(t[0] for t in toks)); tout = int(statistics.mean(t[1] for t in toks))
        same = "reference" if m == REFERENCE else f"{agree}/{len(GOALS)}"
        print(f"{m:38} {statistics.median(times):8.2f} {valid:>3}/{n:<2} {same:>15} {tin:>5}/{tout:<5}")
    print("\nPick the fastest model with valid replies and mostly the same #1 as the reference.")


if __name__ == "__main__":
    main()

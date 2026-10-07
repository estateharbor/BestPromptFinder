"""
LLM search enricher (Pass 2 for /api/search).

TF-IDF retrieves the top candidates; this module then asks Claude to judge how well each
one solves the user's *specific goal* — producing a real Purpose-Match score, goal-tailored
"why" bullets, and a concrete weakness. Results re-rank on the LLM's match.

Activates only when the Anthropic SDK is installed AND a credential is available; otherwise
the recommender falls back to the deterministic match + synthesized explanations.

Model defaults to Claude Sonnet 5 (set LLM_MODEL to override). Thinking is disabled for
low search latency; the judgment is a bounded scoring task.
"""
import os
import sys
import json
import logging
from typing import List, Dict, Any

log = logging.getLogger("prompt_finder")

# Shared daily spend guard (lives at repo root).
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    import budget
except Exception:
    budget = None
import emergent_client

# Search reranking is a bounded scoring task where latency matters most — use a fast model
# (Haiku) by default, independent of LLM_MODEL (which governs grading/preview quality).
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """You are a prompt recommendation judge. You are given a user's GOAL and a list of candidate prompts. For EACH candidate, judge how well it solves THAT specific goal — not its general quality.

Return ONLY a valid JSON array (no prose), one object per candidate id:
{"id": "<id>", "match": <int 0-100, fit to THIS goal>, "why": ["<=2 short reasons this prompt serves the goal>"], "weakness": "<one concrete gap for this goal, max 12 words>"}

Rules: match reflects task/purpose fit to the goal, not polish. A well-built prompt for a different job scores low. Give at most 2 "why" reasons, each under 12 words and specific to the goal. Evaluate each candidate independently. If a prompt does NOT genuinely fit the goal, give it a low match and return an empty "why" list — never invent reasons to recommend a poor fit."""


def available() -> bool:
    if os.getenv("SEARCH_USE_LLM", "1") == "0":
        return False
    if emergent_client.provider() == "emergent":
        return emergent_client.available()
    try:
        import anthropic  # noqa: F401
    except Exception:
        return False
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return True
    return os.path.isdir(os.path.expanduser("~/.config/anthropic"))


def enrich(goal: str, candidates: List[Dict[str, str]],
           model: str = None) -> Dict[str, Dict[str, Any]]:
    """Return {id: {match, why, weakness}} for the candidates, or {} on failure."""
    model = model or os.getenv("SEARCH_MODEL") or DEFAULT_MODEL  # empty env value = default
    use_emergent = emergent_client.provider() == "emergent"
    if not use_emergent:
        try:
            import anthropic
        except Exception:
            return {}

    if budget and not budget.allowed(scope="search"):
        log.warning("[LLM enrich] daily budget reached; using deterministic match.")
        return {}

    payload = {
        "goal": goal,
        "candidates": [{"id": c["id"], "title": c["title"], "prompt": c["prompt"][:400]} for c in candidates],
    }
    try:
        if use_emergent:
            text, usage, model = emergent_client.chat_with_fallback(
                model, SYSTEM, json.dumps(payload, ensure_ascii=False), max_tokens=900, timeout=45)
            if budget:
                budget.record(model, usage["input"], usage["output"], scope="search")
        else:
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model=model,
                max_tokens=900,
                thinking={"type": "disabled"},   # bounded scoring task; keep search snappy
                system=SYSTEM,
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            )
            if budget:
                budget.record(model, resp.usage.input_tokens, resp.usage.output_tokens, scope="search")
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
        start, end = text.find("["), text.rfind("]")
        parsed = json.loads(text[start:end + 1]) if start >= 0 else []
        out: Dict[str, Dict[str, Any]] = {}
        for obj in parsed:
            if isinstance(obj, dict) and "id" in obj:
                out[str(obj["id"])] = {
                    "match": int(obj.get("match", 0)),
                    "why": [str(w) for w in (obj.get("why") or [])][:2],
                    "weakness": str(obj.get("weakness", "")),
                }
        return out
    except Exception as e:
        log.warning("[LLM enrich] failed (%s); using deterministic fallback.", e)
        return {}

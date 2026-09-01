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

DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM = """You are a prompt recommendation judge. You are given a user's GOAL and a list of candidate prompts. For EACH candidate, judge how well it solves THAT specific goal — not its general quality.

Return ONLY a valid JSON array (no prose), one object per candidate id:
{"id": "<id>", "match": <int 0-100, fit to THIS goal>, "why": ["<=4 short reasons this prompt serves the goal>"], "weakness": "<one concrete gap for this goal>"}

Rules: match reflects task/purpose fit to the goal, not polish. A well-built prompt for a different job scores low. Keep each "why" under 12 words and specific to the goal. Evaluate each candidate independently."""


def available() -> bool:
    if os.getenv("SEARCH_USE_LLM", "1") == "0":
        return False
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
    model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
    try:
        import anthropic
    except Exception:
        return {}

    if budget and not budget.allowed():
        log.warning("[LLM enrich] daily budget reached; using deterministic match.")
        return {}

    payload = {
        "goal": goal,
        "candidates": [{"id": c["id"], "title": c["title"], "prompt": c["prompt"][:800]} for c in candidates],
    }
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model,
            max_tokens=2000,
            thinking={"type": "disabled"},   # bounded scoring task; keep search snappy
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
        if budget:
            budget.record(model, resp.usage.input_tokens, resp.usage.output_tokens)
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        start, end = text.find("["), text.rfind("]")
        parsed = json.loads(text[start:end + 1]) if start >= 0 else []
        out: Dict[str, Dict[str, Any]] = {}
        for obj in parsed:
            if isinstance(obj, dict) and "id" in obj:
                out[str(obj["id"])] = {
                    "match": int(obj.get("match", 0)),
                    "why": [str(w) for w in (obj.get("why") or [])][:4],
                    "weakness": str(obj.get("weakness", "")),
                }
        return out
    except Exception as e:
        log.warning("[LLM enrich] failed (%s); using deterministic fallback.", e)
        return {}

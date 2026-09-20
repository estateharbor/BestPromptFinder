"""
Template variable extractor (guided fill).

Given the user's original GOAL and a prompt template with {placeholders}, this asks Claude
to pull a value for each placeholder ONLY when the goal actually provides it — never guessing
or inventing. Missing fields come back empty so the UI can ask the user for them instead of
fabricating (the failure mode the audit flagged: an invented Tampa property, price and yield).

Activates only when the Anthropic SDK + a credential are available and the daily budget
allows; otherwise the caller shows an empty form the user fills in by hand.
"""
import os
import sys
import json
import logging
from typing import List, Dict

log = logging.getLogger("prompt_finder")

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    import budget
except Exception:
    budget = None

# Prefill is a fast, bounded extraction — use a quick model by default for low latency.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """You extract values for a prompt template's placeholders from a user's GOAL.

You are given the GOAL, the TEMPLATE, and a list of PLACEHOLDER names. For each placeholder, return a value ONLY if it is explicitly stated or unambiguously implied by the goal. If the goal does not provide it, return an empty string "" — NEVER guess, invent, or fill with a generic example. Do not fabricate names, numbers, prices, locations, dates or facts.

Return ONLY a JSON object mapping each placeholder name to its string value, e.g. {"topic": "quarterly earnings", "audience": ""}. No prose."""


def available() -> bool:
    if os.getenv("FILL_USE_LLM", "1") == "0":
        return False
    try:
        import anthropic  # noqa: F401
    except Exception:
        return False
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return True
    return os.path.isdir(os.path.expanduser("~/.config/anthropic"))


def extract(goal: str, template: str, variables: List[str], model: str = None) -> Dict[str, str]:
    """Return {variable: value} extracted from the goal (empty string when not present)."""
    model = model or os.getenv("SEARCH_MODEL", DEFAULT_MODEL)
    out = {v: "" for v in variables}
    if not variables or not (goal or "").strip():
        return out
    try:
        import anthropic
    except Exception:
        return out
    if budget and not budget.allowed():
        log.warning("[LLM fill] daily budget reached; returning empty prefill.")
        return out

    payload = {"goal": goal, "template": (template or "")[:1200], "placeholders": variables}
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model,
            max_tokens=600,
            thinking={"type": "disabled"},  # bounded extraction; keep it fast + cheap
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
        if budget:
            budget.record(model, resp.usage.input_tokens, resp.usage.output_tokens)
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        start, end = text.find("{"), text.rfind("}")
        parsed = json.loads(text[start:end + 1]) if start >= 0 else {}
        for k, v in parsed.items():
            if k in out and isinstance(v, str):
                out[k] = v.strip()
        return out
    except Exception as e:
        log.warning("[LLM fill] failed (%s); returning empty prefill.", e)
        return out

"""
Live sample-output preview.

Runs a prompt through Claude and returns a short, representative example of what it
produces — so the UI can "show the result, not just the prompt" for real. Used for
text / coding / data prompts (Anthropic doesn't generate images, so image prompts keep
their representative tile).

Activates only when the Anthropic SDK + a credential are available.
"""
import os
import sys
import logging
from typing import Dict, Any

log = logging.getLogger("prompt_finder")

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    import budget
except Exception:
    budget = None

DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM = """You are demonstrating what an AI prompt produces. Given the prompt below, generate a SHORT, representative example of its output — the kind of answer a capable model would return.

Rules:
- If the prompt expects an input (has placeholders like {topic} or asks for pasted data), invent a brief, plausible example input and use it.
- Output ONLY the example result. Do not preface, explain, or restate the prompt.
- Keep it concise: under 180 words (or a short code block for coding prompts)."""


def available() -> bool:
    if os.getenv("PREVIEW_USE_LLM", "1") == "0":
        return False
    try:
        import anthropic  # noqa: F401
    except Exception:
        return False
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return True
    return os.path.isdir(os.path.expanduser("~/.config/anthropic"))


def generate(prompt: str, model: str = None) -> Dict[str, Any]:
    """Run the prompt and return {output, model}. Raises on hard failure."""
    model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
    if budget and not budget.allowed():
        raise RuntimeError("Daily API budget reached — live preview paused until tomorrow.")
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=700,
        thinking={"type": "disabled"},   # a quick demonstration, not a reasoning task
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt[:2000]}],
    )
    if budget:
        budget.record(model, resp.usage.input_tokens, resp.usage.output_tokens)
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return {"output": text, "model": model}

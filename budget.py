"""
Daily LLM spend guard.

A shared, file-backed cap on Anthropic spend per UTC day, consulted by every LLM entry
point (pipeline judge, search enricher, live preview). When the day's estimated spend
reaches DAILY_BUDGET_USD, further LLM calls are skipped and the code falls back to its
non-LLM path. The tally is stored in the user's home dir so the pipeline and the app —
which run from different working directories — share one budget.

Set DAILY_BUDGET_USD (default 1.0). This is a client-side estimate from token usage; it
complements, and does not replace, a hard spend limit set in the Anthropic Console.
"""
import os
import json
import threading
from datetime import date

# $ per 1M tokens (input, output) — keep in sync with current pricing.
PRICING = {
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5": (10.0, 50.0),
}
_DEFAULT_PRICE = (3.0, 15.0)

_FILE = os.getenv("LLM_BUDGET_FILE") or os.path.expanduser("~/.promptfinder_llm_budget.json")
_lock = threading.Lock()


def cap() -> float:
    try:
        return float(os.getenv("DAILY_BUDGET_USD", "1.0"))
    except ValueError:
        return 1.0


def cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICING.get(model, _DEFAULT_PRICE)
    return input_tokens / 1e6 * pin + output_tokens / 1e6 * pout


def _load() -> dict:
    try:
        with open(_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    if d.get("date") != date.today().isoformat():
        d = {"date": date.today().isoformat(), "spent": 0.0}
    return d


def _save(d: dict) -> None:
    try:
        with open(_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass


def spent_today() -> float:
    with _lock:
        return round(_load().get("spent", 0.0), 6)


def remaining() -> float:
    return max(0.0, cap() - spent_today())


def allowed(min_headroom: float = 0.0) -> bool:
    """True if there is budget left to make another call."""
    return remaining() > min_headroom


def record(model: str, input_tokens: int, output_tokens: int) -> float:
    c = cost(model, input_tokens, output_tokens)
    with _lock:
        d = _load()
        d["spent"] = round(d.get("spent", 0.0) + c, 6)
        _save(d)
    return c

"""
Template extractor (Stage 12).

Turns a concrete scraped prompt into a reusable template with {VARIABLES}, so a
high-scoring one-off becomes a commercial, fill-in-the-blank asset. Example:

  "Write five Instagram posts for my Mumbai real-estate agency targeting
   first-time home buyers."
  ->
  "Write {COUNT} Instagram posts for my {LOCATION} {BUSINESS_TYPE} targeting
   {TARGET_AUDIENCE}."
  variables: [COUNT, LOCATION, BUSINESS_TYPE, TARGET_AUDIENCE]

This is a deterministic, dependency-free pass. It is conservative — it only
parameterizes patterns it is confident about, so it never mangles a prompt. An LLM
pass can enrich it later; the interface (template_prompt + variables) stays the same.
"""
import re
from typing import List, Tuple

_NUMBER_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "twenty", "thirty", "fifty", "hundred",
}

# Ordered rules: (compiled regex, replacement, variable name).
# Each rule replaces the *captured* group (group 1) with {VAR} and records VAR.
_RULES = [
    # existing placeholders of any style -> normalized {VAR}
    (re.compile(r"\$\{\s*([A-Za-z0-9_ ]+?)\s*\}"), "PLACEHOLDER"),      # ${x}
    (re.compile(r"\{\s*([A-Za-z0-9_ ]+?)\s*\}"), "PLACEHOLDER"),        # {x}
    (re.compile(r"\[\s*([A-Z0-9_ ]{2,}?)\s*\]"), "PLACEHOLDER"),        # [X]
    (re.compile(r"<\s*([A-Za-z0-9_ ]+?)\s*>"), "PLACEHOLDER"),          # <x>
]

# Semantic slot rules applied to plain text (group 1 is replaced).
_SLOT_RULES = [
    # counts: "5 posts", "five ideas"
    (re.compile(r"\b(\d{1,3})\b(?=\s+\w)"), "COUNT"),
    (re.compile(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b(?=\s+\w)", re.I), "COUNT"),
    # audience: "targeting first-time home buyers", "aimed at investors", "for developers"
    (re.compile(r"\btargeting\s+([a-z][\w\- ]{3,40}?)(?=[.,;]|\s+(?:in|with|using|about)\b|$)", re.I), "TARGET_AUDIENCE"),
    (re.compile(r"\baimed at\s+([a-z][\w\- ]{3,40}?)(?=[.,;]|$)", re.I), "TARGET_AUDIENCE"),
    # location: "in Mumbai", "in New York"
    (re.compile(r"\bin\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\b"), "LOCATION"),
    # quoted topic: "..." or '...'
    (re.compile(r"[\"“]([^\"”]{3,60})[\"”]"), "TOPIC"),
    # business/product: "my X agency/business/company/startup/brand/shop/store"
    (re.compile(r"\bmy\s+([a-z][\w\- ]{2,40}?)\s+(?=agency|business|company|startup|brand|shop|store|app|product)", re.I), "BUSINESS_TYPE"),
    (re.compile(r"\bmy\s+([\w\- ]{2,40}?\s+(?:product|app|tool|service|saas))\b", re.I), "PRODUCT"),
]


def _uniquify(name: str, used: dict) -> str:
    """Return VAR, VAR_2, ... so repeated slot types don't collide."""
    used[name] = used.get(name, 0) + 1
    return name if used[name] == 1 else f"{name}_{used[name]}"


def extract_template(text: str) -> Tuple[str, List[str]]:
    """Return (template_prompt, variables). If nothing is parameterizable, returns
    the text unchanged and an empty variable list."""
    if not text:
        return text, []
    result = text
    variables: List[str] = []
    used: dict = {}

    # 1) Normalize any pre-existing placeholders to {VAR}.
    for rx, base in _RULES:
        def _repl_ph(m):
            raw = re.sub(r"[^A-Za-z0-9]+", "_", m.group(1).strip()).upper().strip("_")
            name = raw if raw else _uniquify(base, used)
            if name not in variables:
                variables.append(name)
            return "{" + name + "}"
        result = rx.sub(_repl_ph, result)

    # 2) Apply semantic slot rules (first match per rule region).
    for rx, base in _SLOT_RULES:
        def _repl_slot(m):
            name = _uniquify(base, used)
            variables.append(name)
            # Preserve the non-captured surrounding text by replacing only group 1.
            whole = m.group(0)
            captured = m.group(1)
            return whole.replace(captured, "{" + name + "}", 1)
        result, n = rx.subn(_repl_slot, result, count=1)

    # De-dupe variable list, keep order.
    seen = set()
    variables = [v for v in variables if not (v in seen or seen.add(v))]
    return result, variables


def is_template_worthy(text: str, variables: List[str]) -> bool:
    """A prompt is 'template-worthy' if extraction found >= 1 variable."""
    return len(variables) >= 1

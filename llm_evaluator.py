"""
Optional LLM quality evaluator (Stage 6, "Pass 2").

Sends batches of pre-filtered prompts to Claude with the Prompt Quality Evaluator
rubric as the system prompt, and returns per-id JSON scores. Activates only when the
Anthropic SDK is installed AND a credential is available; otherwise the pipeline uses
the deterministic heuristic scorer instead.

Two lanes:
  * Batch API (default) — asynchronous, 50% cheaper. Ideal for the nightly bulk run.
    All 25-prompt chunks are submitted as one batch job, then polled to completion.
  * Synchronous — one request per chunk, results in seconds. Use for small/interactive
    runs by setting use_batch=False (or env LLM_USE_BATCH=0).

Cost-savers baked in:
  * 25 prompts per request (rubric sent once per chunk, not per prompt).
  * Rubric system prompt is marked cache_control:ephemeral so its tokens are cached
    across chunks (Sonnet's min cacheable prefix ~1024 tok covers the ~1.2k rubric).
"""
import os
import json
import time
import logging
from typing import List, Dict, Any

log = logging.getLogger("scraper_agent")

try:
    import budget
except Exception:
    budget = None

# 15 (not 25) per request: a full 25-prompt chunk's JSON scores could exceed MAX_TOKENS
# and truncate, leaving prompts unscored. 15 keeps each chunk's output comfortably in budget.
BATCH_SIZE = 15
DEFAULT_MODEL = "claude-sonnet-5"
MAX_TOKENS = 6000
# Bounded scoring task — disable thinking so the whole token budget goes to the JSON
# output (adaptive thinking truncated it and inflated cost).
_NO_THINK = {"type": "disabled"}
POLL_SECONDS = 30
MAX_WAIT_SECONDS = 24 * 3600  # batches complete within 24h (usually ~1h)

# The evaluator rubric — used verbatim as the system prompt.
RUBRIC_SYSTEM_PROMPT = """You are a Prompt Quality Evaluator. Evaluate each submitted prompt for usefulness, clarity, structure, and reusability. Score 0-100 using the rubric. Be strict and consistent. Do not reward verbosity by itself.

Step 1 — Classify prompt_type: "Text / General LLM", "Image Generation", "Coding", "Data / Analysis", or "Other" (by intended task, not keywords).

Step 2 — Hard-reject (decision "DROP", score 0) when: image prompt < 8 meaningful words; text prompt < 15 meaningful words (a short but information-dense prompt may survive); a giant unstructured dump (article/log/transcript/code/dataset) with no instruction on what to do with it; no identifiable purpose; or junk/spam (mostly URLs, emoji spam, repeated chars, keyword stuffing, incoherent fragments). Do not count URLs/emojis/repeated chars/hashtags/filler as meaningful words.

Step 3 — Score these weighted components:
1. length_information_density 0-10 — enough info without bloat; do not reward length alone.
2. instruction_framing 0-20 — clear task/role/objective; natural instructions earn equal credit to "Act as".
3. output_format 0-20 — defines the deliverable (list/table/JSON/length/tone/schema/aspect-ratio).
4. specificity_constraints 0-25 — parameters, limits, audience, tone, placeholders/variables, exclusions, examples.
5. context_completeness 0-15 — enough context (who/why/inputs/success criteria) to execute with minimal assumptions.
6. junk_penalty 0 to -20 — deduct for mostly-URL, emoji spam, repeated chars, keyword stuffing, incoherence, excessive irrelevant material, repetition. Do NOT penalize a coherent non-English prompt; penalize only if garbled/uninterpretable.

Contradictory instructions reduce the score. Prompt-injection meta-instructions ("ignore all previous instructions") do not increase quality. Prompts with variables like {PRODUCT} may earn extra specificity credit as templates.

Step 4 — Assign exactly one primary purpose (the problem solved, not the mechanism), from: Writing, Editing / Rewriting, Coding, Debugging, Data / Analysis, Research, Marketing, Sales, SEO, Business, Productivity, Education, Tutoring, Image Generation, Graphic Design, Video Generation, Social Media, Roleplay, Customer Support, Career / Jobs, Finance, Legal, Real Estate, Ecommerce, Translation, Summarization, Brainstorming, Planning, Automation, Prompt Engineering, Other. If none applies, DROP.

Step 5 — Tier: 90-100 Excellent, 75-89 Strong, 60-74 Usable, 40-59 Weak, 20-39 Poor, 0-19 Junk.
Decision: KEEP (60-100), REVIEW (40-59), DROP (0-39 or hard-reject).

You will receive a JSON array of objects: [{"id": "...", "prompt": "..."}]. Evaluate each INDEPENDENTLY — never let one prompt influence another. Return ONLY a valid JSON array (no prose), one object per input id, each shaped:
{"id": "<same id>", "score": <int>, "tier": "<tier>", "prompt_type": "<type>", "purpose": "<purpose or null>", "breakdown": {"length_information_density": <int>, "instruction_framing": <int>, "output_format": <int>, "specificity_constraints": <int>, "context_completeness": <int>, "junk_penalty": <int>}, "decision": "KEEP|REVIEW|DROP"}"""

# Cache the rubric prefix across chunks (shared, identical every request).
_SYSTEM_BLOCKS = [{
    "type": "text",
    "text": RUBRIC_SYSTEM_PROMPT,
    "cache_control": {"type": "ephemeral"},
}]


def available() -> bool:
    """True only if the SDK is importable and a credential is resolvable."""
    try:
        import anthropic  # noqa: F401
    except Exception:
        return False
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return True
    # An `ant auth login` profile also works; treat presence of the config as usable.
    cfg = os.path.expanduser("~/.config/anthropic")
    return os.path.isdir(cfg)


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _parse_array(text: str) -> List[Dict[str, Any]]:
    """Tolerantly extract the JSON array from a model response."""
    text = (text or "").strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < 0:
        return []
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return []


def _merge(results: Dict[str, Dict[str, Any]], parsed: List[Dict[str, Any]]):
    for obj in parsed:
        if isinstance(obj, dict) and "id" in obj:
            results[str(obj["id"])] = obj


def evaluate(prompts: List[Dict[str, str]], model: str = None,
             use_batch: bool = None) -> Dict[str, Dict[str, Any]]:
    """Evaluate prompts (list of {id, prompt}). Returns {id: result_dict}.

    Defaults to the Batch API (50% cheaper); set use_batch=False for synchronous.
    """
    model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
    if use_batch is None:
        use_batch = os.getenv("LLM_USE_BATCH", "1") != "0"
    if not prompts:
        return {}
    return _evaluate_batch(prompts, model) if use_batch else _evaluate_sync(prompts, model)


# ------------------------------------------------------------------
# Synchronous lane (fast, full price)
# ------------------------------------------------------------------
def _evaluate_sync(prompts: List[Dict[str, str]], model: str) -> Dict[str, Dict[str, Any]]:
    import anthropic
    client = anthropic.Anthropic()
    results: Dict[str, Dict[str, Any]] = {}

    for batch in _chunks(prompts, BATCH_SIZE):
        if budget and not budget.allowed():
            log.warning("[LLM sync] daily budget reached ($%.2f spent); remaining prompts use heuristic.",
                        budget.spent_today())
            break
        payload = json.dumps(batch, ensure_ascii=False)
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                thinking=_NO_THINK,
                system=_SYSTEM_BLOCKS,
                messages=[{"role": "user", "content": payload}],
            )
            if budget:
                budget.record(model, resp.usage.input_tokens, resp.usage.output_tokens)
            text = "".join(b.text for b in resp.content if b.type == "text")
            _merge(results, _parse_array(text))
        except Exception as e:
            log.warning("[LLM sync] chunk failed (%s); those prompts fall back to heuristic.", e)
    return results


# ------------------------------------------------------------------
# Batch lane (asynchronous, 50% off) — default for nightly runs
# ------------------------------------------------------------------
def _evaluate_batch(prompts: List[Dict[str, str]], model: str) -> Dict[str, Dict[str, Any]]:
    import anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    client = anthropic.Anthropic()
    results: Dict[str, Dict[str, Any]] = {}

    # One request per 25-prompt chunk; each returns a JSON array for its ids.
    chunks = list(_chunks(prompts, BATCH_SIZE))

    # Batch bills 50% off but is all-or-nothing, so it cannot be stopped mid-flight.
    # Pre-estimate each chunk's batch cost and submit only as many chunks as fit the
    # remaining daily budget — the rest fall back to the heuristic scorer. This makes it
    # impossible for a batch to push the day's spend over the cap.
    if budget:
        remaining = budget.remaining()
        _RUBRIC_TOK = 1300          # cached rubric system prompt (~conservative)
        # Batch is all-or-nothing, so the guard must OVER-estimate to keep actual spend
        # under the cap. Real runs came in ~18% above the naive estimate (higher per-prompt
        # JSON output than 110 tok), so raise the per-prompt output estimate and add a
        # safety margin — the guard should undershoot the budget, never overshoot it.
        _SAFETY = 1.30
        fitted, running = [], 0.0
        for chunk in chunks:
            in_tok = _RUBRIC_TOK + len(json.dumps(chunk, ensure_ascii=False)) // 4
            out_tok = 160 * len(chunk) + 300        # conservative per-prompt JSON estimate
            est = budget.cost(model, in_tok, out_tok) * 0.5 * _SAFETY   # 50% batch discount + margin
            if running + est > remaining:
                break
            running += est
            fitted.append(chunk)
        if not fitted:
            log.warning("[LLM batch] $%.2f left in today's budget — not enough for a chunk; heuristic only.",
                        remaining)
            return results
        if len(fitted) < len(chunks):
            log.warning("[LLM batch] Budget $%.2f fits %d of %d chunks (~$%.2f); the rest use heuristic.",
                        remaining, len(fitted), len(chunks), running)
        chunks = fitted

    requests = [
        Request(
            custom_id=f"chunk-{i}",
            params=MessageCreateParamsNonStreaming(
                model=model,
                max_tokens=MAX_TOKENS,
                thinking=_NO_THINK,
                system=_SYSTEM_BLOCKS,
                messages=[{"role": "user", "content": json.dumps(chunk, ensure_ascii=False)}],
            ),
        )
        for i, chunk in enumerate(chunks)
    ]

    log.info("[LLM batch] Submitting %d prompts in %d requests (model=%s, 50%% batch rate)...",
             len(prompts), len(requests), model)
    batch = client.messages.batches.create(requests=requests)
    log.info("[LLM batch] Batch %s created; polling until complete (usually ~1h)...", batch.id)

    # Poll to completion.
    waited = 0
    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        if waited >= MAX_WAIT_SECONDS:
            log.warning("[LLM batch] Timed out after %ds; results incomplete.", waited)
            return results
        time.sleep(POLL_SECONDS)
        waited += POLL_SECONDS

    # Collect results (arrive in any order — keyed by custom_id).
    ok = err = 0
    for result in client.messages.batches.results(batch.id):
        if result.result.type == "succeeded":
            msg = result.result.message
            if budget and getattr(msg, "usage", None):
                # Batch is 50% off; record half the standard cost.
                budget.record(model, msg.usage.input_tokens // 2, msg.usage.output_tokens // 2)
            text = "".join(b.text for b in msg.content if b.type == "text")
            _merge(results, _parse_array(text))
            ok += 1
        else:
            err += 1
            log.warning("[LLM batch] %s: %s", result.custom_id, result.result.type)
    log.info("[LLM batch] Done: %d chunks succeeded, %d failed; %d prompts scored.",
             ok, err, len(results))
    return results

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


# Emergent Universal Key: an OpenAI-compatible proxy in front of Claude/GPT/Gemini, billed to
# Emergent credits. Used when LLM_PROVIDER=emergent, or when only EMERGENT_LLM_KEY is set.
EMERGENT_BASE_URL = os.getenv("EMERGENT_BASE_URL", "https://integrations.emergentagent.com/llm/v1")


def provider() -> str:
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    if os.getenv("EMERGENT_LLM_KEY") and not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        return "emergent"
    return "anthropic"


def available() -> bool:
    """True only if the SDK is importable and a credential is resolvable."""
    if provider() == "emergent":
        return bool(os.getenv("EMERGENT_LLM_KEY"))
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
    if not prompts:
        return {}
    if provider() == "emergent":
        return _evaluate_emergent(prompts, model or os.getenv("EMERGENT_MODEL") or os.getenv("LLM_MODEL", DEFAULT_MODEL))
    model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
    if use_batch is None:
        use_batch = os.getenv("LLM_USE_BATCH", "1") != "0"
    return _evaluate_batch(prompts, model) if use_batch else _evaluate_sync(prompts, model)


# ------------------------------------------------------------------
# Emergent lane (OpenAI-compatible chat completions; no batch discount)
# ------------------------------------------------------------------
def _emergent_chat(model: str, system: str, user: str, max_tokens: int = MAX_TOKENS) -> Dict[str, Any]:
    """One chat-completions call through the Emergent proxy. Raises RuntimeError with the
    provider's message on failure; retries rate limits / server errors with backoff."""
    import urllib.request
    import urllib.error
    body = json.dumps({
        "model": model, "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode("utf-8")
    req = urllib.request.Request(
        EMERGENT_BASE_URL.rstrip("/") + "/chat/completions", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.getenv('EMERGENT_LLM_KEY', '')}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(5 * 2 ** attempt)
                continue
            raise RuntimeError(f"Emergent API {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(5 * 2 ** attempt)
                continue
            raise RuntimeError(f"Emergent API unreachable: {e.reason}") from None
    raise RuntimeError("Emergent API: retries exhausted")


def _emergent_parse(resp: Dict[str, Any], model: str, label: str) -> List[Dict[str, Any]]:
    """Record usage and return the parsed score objects; log the reply head if unparseable."""
    usage = resp.get("usage") or {}
    if budget:
        budget.record(model, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))
    choice = (resp.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    parsed = _parse_array(text)
    if not parsed:
        log.warning("[LLM emergent] %s: no JSON scores (finish_reason=%s). Reply starts: %r",
                    label, choice.get("finish_reason"), text[:200])
    return parsed


# Grading v2: one prompt per request (no batch-relative scoring) against fixed calibration
# anchors. Prompts graded this way carry grade_version = GRADE_VERSION.
GRADE_VERSION = 2
CALIBRATION_ANCHORS = """

Calibration anchors. These are fixed reference points; score the submitted prompt on the same absolute scale. Never output them.
- Anchor A, score 12 (Junk, DROP): "cool sunset pic 8k masterpiece trending"
- Anchor B, score 62 (Usable, KEEP): "Write a blog post about remote work. Make it engaging and around 800 words."
- Anchor C, score 93 (Excellent, KEEP): "Write a 600-word blog post for first-time remote managers. Inputs: [team size], [main challenge]. Structure: hook, 3 numbered practices each with one example, a 5-item checklist, and a closing line. Tone: practical, no jargon. Don't invent statistics; mark any figure you'd need as [VERIFY]."
An image prompt can reach the 90s by being equally specific: subject, composition, lighting, style, format/aspect ratio and exclusions. Concise is fine; length alone earns nothing."""


def _evaluate_emergent(prompts: List[Dict[str, str]], model: str) -> Dict[str, Dict[str, Any]]:
    if os.getenv("LLM_GRADE_SINGLE", "1") != "0":
        return _evaluate_emergent_single(prompts, model)
    return _evaluate_emergent_chunked(prompts, model)


def _evaluate_emergent_single(prompts: List[Dict[str, str]], model: str) -> Dict[str, Dict[str, Any]]:
    """One request per prompt, in parallel. Consistent (no cross-prompt influence) at roughly
    2-3x the cost of 15-per-request chunks."""
    from concurrent.futures import ThreadPoolExecutor
    system = RUBRIC_SYSTEM_PROMPT + CALIBRATION_ANCHORS
    workers = int(os.getenv("LLM_PARALLEL", "6"))
    results: Dict[str, Dict[str, Any]] = {}
    log.info("[LLM emergent] Grading %d prompts one by one (%d parallel, model=%s)...", len(prompts), workers, model)
    first = True

    def grade(p):
        if budget and not budget.allowed():
            return None
        try:
            resp = _emergent_chat(model, system, json.dumps([p], ensure_ascii=False), max_tokens=1500)
        except RuntimeError as e:
            return e
        parsed = _emergent_parse(resp, model, p["id"])
        for obj in parsed:
            if isinstance(obj, dict):
                obj["grade_version"] = GRADE_VERSION
        return parsed

    if prompts:  # fail fast on a bad key / model / endpoint before fanning out
        out = grade(prompts[0])
        if isinstance(out, RuntimeError):
            raise out
        _merge(results, out or [])
        first = False
    done = 1
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for out in ex.map(grade, prompts[1:] if not first else prompts):
            done += 1
            if isinstance(out, RuntimeError):
                log.warning("[LLM emergent] a prompt failed (%s); it stays on its previous score.", out)
            elif out:
                _merge(results, out)
            if done % 50 == 0:
                log.info("[LLM emergent] %d/%d graded, $%.2f spent today.", len(results), len(prompts),
                         budget.spent_today() if budget else -1.0)
    if budget and not budget.allowed():
        log.warning("[LLM emergent] daily budget reached; %d of %d graded — re-run to continue.",
                    len(results), len(prompts))
    return results


def _evaluate_emergent_chunked(prompts: List[Dict[str, str]], model: str) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    chunks = list(_chunks(prompts, BATCH_SIZE))
    log.info("[LLM emergent] Grading %d prompts in %d requests (model=%s)...", len(prompts), len(chunks), model)
    for i, chunk in enumerate(chunks, 1):
        if budget and not budget.allowed():
            log.warning("[LLM emergent] daily budget reached ($%.2f spent); %d chunks left for next run.",
                        budget.spent_today(), len(chunks) - i + 1)
            break
        try:
            resp = _emergent_chat(model, RUBRIC_SYSTEM_PROMPT, json.dumps(chunk, ensure_ascii=False))
        except RuntimeError as e:
            if i == 1:
                raise  # first call failing = bad key / model / endpoint: surface it, don't loop
            log.warning("[LLM emergent] chunk %d failed (%s); those prompts stay heuristic.", i, e)
            continue
        _merge(results, _emergent_parse(resp, model, f"chunk {i}"))
        # Anything the chunk reply didn't score (truncated or malformed JSON): retry one by one,
        # so a single awkward prompt can't sink the other fourteen.
        missing = [p for p in chunk if p["id"] not in results]
        for p in missing:
            if budget and not budget.allowed():
                break
            try:
                one = _emergent_chat(model, RUBRIC_SYSTEM_PROMPT, json.dumps([p], ensure_ascii=False), max_tokens=1500)
                _merge(results, _emergent_parse(one, model, p["id"]))
            except RuntimeError as e:
                log.warning("[LLM emergent] %s failed (%s); stays heuristic.", p["id"], e)
        if i % 5 == 0:
            log.info("[LLM emergent] %d/%d chunks done, %d prompts scored, $%.2f spent today.",
                     i, len(chunks), len(results), budget.spent_today() if budget else -1.0)
    return results


def ping() -> None:
    """Connectivity check: one tiny grading call. Prints provider, model and the outcome."""
    prov = provider()
    model = os.getenv("EMERGENT_MODEL") or os.getenv("LLM_MODEL", DEFAULT_MODEL)
    print(f"provider={prov} model={model} key_set={bool(os.getenv('EMERGENT_LLM_KEY') if prov == 'emergent' else os.getenv('ANTHROPIC_API_KEY'))}")
    sample = [{"id": "ping", "prompt": "Write a 150-word product description for [product] aimed at [audience], "
                                      "using only these facts: [facts]. Output: headline, description, 3 bullets."}]
    try:
        r = evaluate(sample, use_batch=False)
    except Exception as e:
        print(f"FAILED: {e}")
        raise SystemExit(1)
    print("OK:", json.dumps(r.get("ping"), ensure_ascii=False)[:300] if r.get("ping") else "call worked but no score parsed")


if __name__ == "__main__":
    import sys
    if "--ping" in sys.argv:
        ping()


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

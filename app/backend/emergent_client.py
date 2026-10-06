"""
Minimal client for the Emergent Universal Key: an OpenAI-compatible chat-completions proxy
in front of Claude / GPT / Gemini, billed to Emergent credits.

Selected by LLM_PROVIDER=emergent, or automatically when EMERGENT_LLM_KEY is set and no
Anthropic credential is. Notes learned in production:
  - claude-sonnet-5 rejects `temperature` (only the default is allowed), so we never send it.
  - replies can be slow; reads use a generous timeout and transient errors are retried.
"""
import json
import os
import time
import urllib.error
import urllib.request
from typing import Dict, Generator, Tuple

BASE_URL = os.getenv("EMERGENT_BASE_URL", "https://integrations.emergentagent.com/llm/v1")


def provider() -> str:
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    if os.getenv("EMERGENT_LLM_KEY") and not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        return "emergent"
    return "anthropic"


def available() -> bool:
    return bool(os.getenv("EMERGENT_LLM_KEY"))


def default_model(fallback: str) -> str:
    return os.getenv("EMERGENT_MODEL") or fallback


def _request(model: str, system: str, user: str, max_tokens: int, stream: bool) -> urllib.request.Request:
    body = {"model": model, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    return urllib.request.Request(
        BASE_URL.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.getenv('EMERGENT_LLM_KEY', '')}"})


def _open(req: urllib.request.Request, timeout: int):
    for attempt in range(3):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 * 2 ** attempt)
                continue
            raise RuntimeError(f"Emergent API {e.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if attempt < 2:
                time.sleep(2 * 2 ** attempt)
                continue
            raise RuntimeError(f"Emergent API unreachable: {getattr(e, 'reason', e)}") from None


def chat(model: str, system: str, user: str, max_tokens: int = 700, timeout: int = 120) -> Tuple[str, Dict[str, int]]:
    """Return (text, usage) for one completion."""
    with _open(_request(model, system, user, max_tokens, stream=False), timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    usage = data.get("usage") or {}
    return text, {"input": int(usage.get("prompt_tokens") or 0), "output": int(usage.get("completion_tokens") or 0)}


def stream(model: str, system: str, user: str, max_tokens: int = 700, timeout: int = 120,
           usage_out: Dict[str, int] = None) -> Generator[str, None, None]:
    """Yield text deltas as they arrive (server-sent events). Fills usage_out at the end when
    the proxy reports usage."""
    r = _open(_request(model, system, user, max_tokens, stream=True), timeout)
    try:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                event = json.loads(payload)
            except ValueError:
                continue
            if usage_out is not None and event.get("usage"):
                u = event["usage"]
                usage_out["input"] = int(u.get("prompt_tokens") or 0)
                usage_out["output"] = int(u.get("completion_tokens") or 0)
            for choice in event.get("choices") or []:
                delta = (choice.get("delta") or {}).get("content")
                if delta:
                    yield delta
    finally:
        r.close()

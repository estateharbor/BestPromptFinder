import os
import re
import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from typing import List, Dict, Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv is optional; env vars can still be set by the shell.
    pass


# ==========================================
# LOGGING & SHARED HTTP SESSION
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scraper_agent")


def build_session(total_retries: int = 3, backoff: float = 0.5) -> requests.Session:
    """A requests.Session with automatic retry/backoff on rate limits and 5xx."""
    session = requests.Session()
    retry = Retry(
        total=total_retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = build_session()


# Common "smart" / typographic characters → plain ASCII equivalents.
_PUNCT_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",   # single quotes
    "“": '"', "”": '"', "„": '"', "‟": '"',   # double quotes
    "–": "-", "—": "-", "―": "-", "−": "-",   # dashes
    "…": "...",                                                # ellipsis
    " ": " ", " ": " ", " ": " ",                  # non-breaking/thin spaces
    "•": "*", "·": "*",                                  # bullets
    "′": "'", "″": '"',                                  # prime marks
}
_PUNCT_TABLE = str.maketrans(_PUNCT_MAP)


def normalize_text(text: Any) -> Any:
    """Replace smart quotes/dashes/etc. with ASCII; leave non-strings untouched."""
    if not isinstance(text, str):
        return text
    return text.translate(_PUNCT_TABLE)


def strip_html(text: str) -> str:
    """Turn an HTML snippet into readable plain text."""
    if not text:
        return ""
    text = unescape(text)
    text = re.sub(r"<\s*(p|br|/p|li)\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ==========================================
# 1. DATA SCHEMA
# ==========================================
class PromptData:
    """Standardized schema for extracted prompt data."""
    def __init__(self, platform: str, title: str, prompt_text: str,
                 model_target: str, category: str, url: str,
                 engagement: int = 0):
        self.platform = platform
        self.title = title
        self.prompt_text = prompt_text
        self.model_target = model_target
        self.category = category
        self.url = url
        self.engagement = engagement          # raw review signal (stars/points/votes/likes)
        self.quality_score = 0                # 0-100, filled by the quality gate
        self.purpose = ""                     # use-case tag, filled by the quality gate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quality_score": self.quality_score,
            "purpose": self.purpose,
            "platform": self.platform,
            "title": self.title,
            "prompt_text": self.prompt_text,
            "model_target": self.model_target,
            "category": self.category,
            "engagement": self.engagement,
            "url": self.url,
        }


# ==========================================
# 2. ZENROWS API MANAGER (For heavily defended sites)
# ==========================================
class ZenRowsManager:
    """Handles communication with the ZenRows Scraping API."""

    API_URL = "https://api.zenrows.com/v1/"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_html(self, target_url: str, js_render: bool = False,
                   antibot: bool = False, premium_proxy: bool = False,
                   js_instructions: Optional[str] = None) -> str:

        if not self.api_key or self.api_key == "YOUR_ZENROWS_API_KEY":
            log.error("[ZenRows] API key missing. Set ZENROWS_API_KEY in your .env.")
            return ""

        params = {
            "url": target_url,
            "apikey": self.api_key,
        }

        if js_render:
            params["js_render"] = "true"
        if antibot:
            params["antibot"] = "true"
        if premium_proxy:
            params["premium_proxy"] = "true"
        if js_instructions:
            params["js_instructions"] = js_instructions

        try:
            log.info("[ZenRows] Dispatching request for %s ...", target_url)
            response = SESSION.get(self.API_URL, params=params, timeout=60)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            log.error("[ZenRows] Network error: %s", e)
            if getattr(e, "response", None) is not None:
                log.error("[ZenRows] Details: %s", e.response.text)
            return ""


# ==========================================
# 3. EXTRACTION STRATEGIES (ROUTING)
# ==========================================
class ScraperStrategy(ABC):
    """Base abstract class for all scraping strategies."""

    def __init__(self, zenrows_manager: ZenRowsManager):
        self.zenrows_manager = zenrows_manager

    @abstractmethod
    def extract(self, config: Dict[str, Any]) -> List[PromptData]:
        pass


# --- LEGACY / EXPERIMENTAL SCRAPERS ---

class APIScraper(ScraperStrategy):
    """Strategy for API/SDK Targets (e.g., LangChain Hub)."""
    def extract(self, config: Dict[str, Any]) -> List[PromptData]:
        url = config.get("url", "https://api.smith.langchain.com/hub/repos")
        api_key = config.get("langchain_api_key", "YOUR_LANGSMITH_API_KEY")
        headers = {"x-api-key": api_key}
        results = []
        try:
            response = SESSION.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            for repo in data.get("repos", [])[:20]:
                results.append(PromptData(
                    platform="LangChain Hub",
                    title=repo.get("repo_handle", "Unknown"),
                    prompt_text=repo.get("description", "Hidden behind commit hash") or "No description",
                    model_target="Multi-Agent/LLM",
                    category="Development",
                    url=f"https://smith.langchain.com/hub/{repo.get('repo_handle')}",
                ))
        except Exception as e:
            log.warning("[LangChain Hub] %s", e)
        return results


class StaticWebScraper(ScraperStrategy):
    """Strategy for The Prompt Index using ZenRows."""
    def extract(self, config: Dict[str, Any]) -> List[PromptData]:
        url = config.get("url")
        results = []
        html_content = self.zenrows_manager.fetch_html(url, js_render=False, antibot=True)
        if not html_content:
            return results

        soup = BeautifulSoup(html_content, "html.parser")
        cards = soup.find_all("div", class_="prompt-card-modern")

        for card in cards:
            try:
                title_elem = card.find(class_="prompt-title")
                title = title_elem.text.strip() if title_elem else "No Title"
                desc_elem = card.find(class_="prompt-description")
                prompt_text = desc_elem.text.strip() if desc_elem else "No Text"

                results.append(PromptData(
                    platform="The Prompt Index", title=title, prompt_text=prompt_text,
                    model_target="ChatGPT/General", category="General",
                    url="https://thepromptindex.com",
                ))
            except Exception as e:
                log.debug("[The Prompt Index] card skipped: %s", e)
                continue
        return results


# --- TIER 1 LEGAL API SCRAPERS ---

class HuggingFaceScraper(ScraperStrategy):
    """Pulls CC0/MIT/permissive prompt datasets from HF Datasets Server REST API (paginated)."""
    PAGE_SIZE = 100
    # Candidate column names, in priority order, across the various prompt datasets.
    # (instruction/question unlock the big instruction-tuning datasets: Dolly, Alpaca, OpenOrca, ...)
    PROMPT_COLS = ["prompt", "Prompt", "prompts", "instruction", "question",
                   "text", "long_prompt", "short_prompt", "content"]
    TITLE_COLS = ["act", "title", "name", "role", "category", "short_prompt", "image_description"]

    def _pick(self, row: Dict[str, Any], candidates: List[str]) -> str:
        for col in candidates:
            val = row.get(col)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""

    def extract(self, config: Dict[str, Any]) -> List[PromptData]:
        dataset = config.get("dataset", "fka/prompts.chat")
        hf_config = config.get("hf_config", "default")
        split = config.get("split", "train")
        max_rows = config.get("max_rows", 300)
        category = config.get("category", "Dataset")
        model_target = config.get("model_target", "General")
        results = []

        log.info("[HuggingFace] Fetching %s (up to %d rows)...", dataset, max_rows)
        offset = 0
        try:
            while offset < max_rows:
                length = min(self.PAGE_SIZE, max_rows - offset)
                url = (
                    "https://datasets-server.huggingface.co/rows"
                    f"?dataset={dataset}&config={hf_config}&split={split}"
                    f"&offset={offset}&length={length}"
                )
                response = SESSION.get(url, timeout=15)
                response.raise_for_status()
                rows = response.json().get("rows", [])
                if not rows:
                    break

                for row in rows:
                    data = row.get("row", {})
                    prompt_text = self._pick(data, self.PROMPT_COLS)
                    if not prompt_text:
                        continue
                    title = self._pick(data, self.TITLE_COLS) or (prompt_text[:60] + "...")
                    results.append(PromptData(
                        platform="Hugging Face",
                        title=title,
                        prompt_text=prompt_text,
                        model_target=model_target,
                        category=category,
                        url=f"https://huggingface.co/datasets/{dataset}",
                        ))
                offset += len(rows)
        except Exception as e:
            log.warning("[HuggingFace] %s", e)
        return results


class MCPRegistryScraper(ScraperStrategy):
    """Pulls permissively licensed Agent configs from the MCP Registry."""
    def extract(self, config: Dict[str, Any]) -> List[PromptData]:
        url = "https://registry.modelcontextprotocol.io/v0/servers?limit=50"
        results = []

        log.info("[MCP Registry] Fetching servers...")
        try:
            response = SESSION.get(url, timeout=15)
            response.raise_for_status()
            payload = response.json()
            # API returns {"servers": [...]} where each entry is {"server": {...}, "_meta": {...}}.
            entries = payload.get("servers", payload) if isinstance(payload, dict) else payload

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                server = entry.get("server", entry)
                title = server.get("title") or server.get("name", "Unknown")
                description = server.get("description", "").strip()

                # Build real, usable content: what it is + how to reach/install it.
                parts = [description] if description else []
                remotes = [r.get("url") for r in server.get("remotes", []) if r.get("url")]
                if remotes:
                    parts.append("Endpoints: " + ", ".join(remotes))
                packages = [
                    f"{p.get('registryType', '')}:{p.get('identifier', '')}".strip(":")
                    for p in server.get("packages", [])
                    if p.get("identifier")
                ]
                if packages:
                    parts.append("Install: " + ", ".join(packages))
                if server.get("version"):
                    parts.append(f"Version {server['version']}")

                repo = server.get("repository") or {}
                repo_url = repo.get("url") if isinstance(repo, dict) else None
                landing = repo_url or (remotes[0] if remotes else None)

                results.append(PromptData(
                    platform="MCP Registry",
                    title=title,
                    prompt_text="\n".join(parts) or "No description",
                    model_target="MCP Agent",
                    category="Agent Config",
                    url=landing or "https://modelcontextprotocol.io",
                ))
        except Exception as e:
            log.warning("[MCP Registry] %s", e)
        return results


class HackerNewsScraper(ScraperStrategy):
    """Discovers prompt discussions via HN Algolia, fetching each story's real text/top comments."""
    ITEM_URL = "https://hn.algolia.com/api/v1/items/{}"
    TOP_COMMENTS = 3
    MAX_TEXT = 2000

    def _fetch_content(self, hit: Dict[str, Any]) -> Optional[PromptData]:
        object_id = hit.get("objectID")
        try:
            item = SESSION.get(self.ITEM_URL.format(object_id), timeout=15).json()
        except Exception as e:
            log.debug("[Hacker News] item %s failed: %s", object_id, e)
            item = {}

        # Prefer the self-post body; otherwise the most substantial top comments.
        body = strip_html(item.get("text", ""))
        if not body:
            comments = [
                strip_html(c.get("text", ""))
                for c in item.get("children", [])
                if c.get("text")
            ]
            comments = [c for c in comments if len(c) > 40]
            comments.sort(key=len, reverse=True)
            body = "\n\n---\n\n".join(comments[:self.TOP_COMMENTS])

        if not body:
            body = "(No inline text; see linked discussion.)"

        return PromptData(
            platform="Hacker News",
            title=hit.get("title", "Unknown"),
            prompt_text=body[:self.MAX_TEXT],
            model_target="General",
            category="Discovery",
            url=hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}",
            engagement=hit.get("points", 0),
        )

    def extract(self, config: Dict[str, Any]) -> List[PromptData]:
        url = "https://hn.algolia.com/api/v1/search"
        max_pages = config.get("max_pages", 3)
        hits: List[Dict[str, Any]] = []

        log.info("[Hacker News] Searching Algolia for 'system prompt'...")
        try:
            for page in range(max_pages):
                params = {
                    "query": "system prompt",
                    "tags": "story",
                    "numericFilters": "points>20",
                    "page": page,
                }
                response = SESSION.get(url, params=params, timeout=15)
                response.raise_for_status()
                data = response.json()
                page_hits = data.get("hits", [])
                if not page_hits:
                    break
                hits.extend(page_hits)
                if page >= data.get("nbPages", 1) - 1:
                    break
        except Exception as e:
            log.warning("[Hacker News] search failed: %s", e)
            return []

        # Fetch the real content for each story concurrently.
        results: List[PromptData] = []
        log.info("[Hacker News] Fetching real content for %d stories...", len(hits))
        with ThreadPoolExecutor(max_workers=8) as pool:
            for pd in pool.map(self._fetch_content, hits):
                if pd:
                    results.append(pd)
        return results


class GitHubScraper(ScraperStrategy):
    """Mines GitHub via REST API for MIT/CC0 prompt repos (paginated)."""
    def extract(self, config: Dict[str, Any]) -> List[PromptData]:
        api_key = config.get("github_token", "YOUR_GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github+json"}
        if api_key and api_key != "YOUR_GITHUB_TOKEN":
            headers["Authorization"] = f"Bearer {api_key}"

        max_pages = config.get("max_pages", 3)
        query = config.get("query", "chatgpt+prompt+license:mit")
        results = []

        log.info("[GitHub] Searching repos for '%s'...", query)
        try:
            for page in range(1, max_pages + 1):
                url = (
                    "https://api.github.com/search/repositories"
                    f"?q={query}&sort=stars&order=desc"
                    f"&per_page=30&page={page}"
                )
                response = SESSION.get(url, headers=headers, timeout=15)
                if response.status_code in (401, 403):
                    log.warning("[GitHub] Invalid/missing token or rate limit hit.")
                    break
                response.raise_for_status()
                items = response.json().get("items", [])
                if not items:
                    break

                for item in items:
                    results.append(PromptData(
                        platform="GitHub",
                        title=item.get("full_name", "Unknown Repo"),
                        prompt_text=item.get("description") or "No description available.",
                        model_target="Multi-Agent/LLM",
                        category="Open Source Repository",
                        url=item.get("html_url", ""),
                        engagement=item.get("stargazers_count", 0),
                    ))
        except Exception as e:
            log.warning("[GitHub] %s", e)
        return results


class KaggleScraper(ScraperStrategy):
    """Searches Kaggle Datasets API for CC licensed prompt datasets."""
    def extract(self, config: Dict[str, Any]) -> List[PromptData]:
        username = config.get("kaggle_username", "YOUR_KAGGLE_USERNAME")
        key = config.get("kaggle_key", "YOUR_KAGGLE_KEY")
        url = "https://www.kaggle.com/api/v1/datasets/list?search=prompts"
        results = []

        if username == "YOUR_KAGGLE_USERNAME" or key == "YOUR_KAGGLE_KEY":
            log.warning("[Kaggle] Credentials missing. Set KAGGLE_USERNAME / KAGGLE_KEY.")
            return results

        log.info("[Kaggle] Searching for prompt datasets...")
        try:
            response = SESSION.get(url, auth=(username, key), timeout=15)
            response.raise_for_status()
            datasets = response.json()

            for ds in datasets[:20]:
                # Skip low-usability datasets outright (usabilityRating is 0-1).
                if ds.get("usabilityRating", 0) < 0.7:
                    continue
                results.append(PromptData(
                    platform="Kaggle",
                    title=ds.get("title", "Unknown"),
                    prompt_text=f"Dataset description: {ds.get('subtitle', '')}",
                    model_target="General",
                    category="Dataset",
                    url=f"https://www.kaggle.com/{ds.get('ref', '')}",
                    engagement=ds.get("voteCount", 0),
                ))
        except Exception as e:
            log.warning("[Kaggle] %s", e)
        return results


class PromptHeroScraper(ScraperStrategy):
    """Scrapes PromptHero listing pages via ZenRows (JS render + antibot).

    The visible prompt text lives in each card image's alt attribute
    (prefixed 'AI generated: '); the full slug lives in the /prompt/ href.
    """
    BASE = "https://prompthero.com"

    def extract(self, config: Dict[str, Any]) -> List[PromptData]:
        listing = config.get("listing", "chatgpt-prompts")
        category = config.get("category", "Image/Text Generation")
        model_target = config.get("model_target", "Midjourney/ChatGPT")
        results = []

        page_url = f"{self.BASE}/{listing}"
        html_content = self.zenrows_manager.fetch_html(page_url, js_render=True, antibot=True)
        if not html_content:
            return results

        soup = BeautifulSoup(html_content, "html.parser")
        seen = set()
        for a in soup.select('a[href*="/prompt/"]'):
            href = a.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            img = a.find("img")
            alt = (img.get("alt") if img else "") or ""
            prompt_text = re.sub(r"^\s*AI generated:\s*", "", alt).strip()
            if not prompt_text:
                continue
            title = prompt_text[:60] + ("..." if len(prompt_text) > 60 else "")
            # Best-effort like count: first number near a heart icon in the card container.
            likes = 0
            card = a
            for _ in range(3):
                if card.parent:
                    card = card.parent
            if card.select_one('[class*="heart"]'):
                m = re.search(r"\b(\d{1,6})\b", card.get_text(" ", strip=True))
                likes = int(m.group(1)) if m else 0
            results.append(PromptData(
                platform="PromptHero",
                title=title,
                prompt_text=prompt_text,
                model_target=model_target,
                category=category,
                url=self.BASE + href if href.startswith("/") else href,
                engagement=likes,
            ))
        return results


class RedditScraper(ScraperStrategy):
    """Pulls prompts from subreddits via Reddit's official OAuth API.

    Requires a free Reddit 'script' app: set REDDIT_CLIENT_ID and
    REDDIT_CLIENT_SECRET in .env. Skips gracefully if absent.
    """
    UA = "legal-ai-prompts/1.0 (by u/legal_ai_prompts)"

    def _token(self, client_id: str, client_secret: str) -> Optional[str]:
        try:
            resp = SESSION.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=(client_id, client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": self.UA},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get("access_token")
        except Exception as e:
            log.warning("[Reddit] token request failed: %s", e)
            return None

    def extract(self, config: Dict[str, Any]) -> List[PromptData]:
        client_id = config.get("reddit_client_id", "")
        client_secret = config.get("reddit_client_secret", "")
        subreddits = config.get("subreddits", ["PromptEngineering", "ChatGPTPromptGenius"])
        limit = config.get("limit", 50)
        results = []

        if not client_id or not client_secret:
            log.warning("[Reddit] Credentials missing. Set REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET in .env.")
            return results

        token = self._token(client_id, client_secret)
        if not token:
            return results

        headers = {"Authorization": f"Bearer {token}", "User-Agent": self.UA}
        for sub in subreddits:
            try:
                url = f"https://oauth.reddit.com/r/{sub}/top?t=month&limit={limit}"
                resp = SESSION.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
                children = resp.json().get("data", {}).get("children", [])
                for child in children:
                    d = child.get("data", {})
                    body = (d.get("selftext") or "").strip()
                    if not body:
                        continue  # skip pure link posts with no prompt text
                    if d.get("upvote_ratio", 1.0) < 0.85:
                        continue  # controversial / low-signal
                    results.append(PromptData(
                        platform="Reddit",
                        title=d.get("title", "Unknown"),
                        prompt_text=body[:2000],
                        model_target="General",
                        category=f"r/{sub}",
                        url="https://www.reddit.com" + d.get("permalink", ""),
                        engagement=d.get("score", 0),
                    ))
            except Exception as e:
                log.warning("[Reddit:r/%s] %s", sub, e)
        return results


class CangheGalleryScraper(ScraperStrategy):
    """GPT-Image2 Prompt Gallery (canghe.ai) — 500+ detailed image-gen prompts.

    Reads the gallery's public cases.json. Each case carries the full prompt, a title,
    a category, and (usually) a source URL, so provenance is preserved.
    """
    def extract(self, config: Dict[str, Any]) -> List[PromptData]:
        url = config.get("url", "https://gpt-image2.canghe.ai/cases.json")
        results = []
        log.info("[Canghe Gallery] Fetching GPT-Image2 prompt cases...")
        try:
            resp = SESSION.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            cases = resp.json().get("cases", [])
            for c in cases:
                prompt = (c.get("prompt") or "").strip()
                if not prompt:
                    continue
                title = (c.get("title") or "Untitled").strip()[:80]
                results.append(PromptData(
                    platform="GPT-Image2 Gallery",
                    title=title,
                    prompt_text=prompt,
                    model_target="GPT-Image",
                    category=c.get("category") or "Image Generation",
                    url=c.get("sourceUrl") or "https://gpt-image2.canghe.ai",
                ))
        except Exception as e:
            log.warning("[Canghe Gallery] %s", e)
        return results


class LlmCuratedScraper(ScraperStrategy):
    """Prompts you sourced/drafted with Claude, ChatGPT, or Gemini and pasted in.

    Reads a LOCAL json file (no network) so you can paste new prompts any time and
    just re-run the pipeline — dedup, AI grading, and serving all pick them up.

    The file is a JSON array. Each item needs at minimum a `title` and a `prompt`
    (aliases `prompt_text`/`text`/`template`/`body` also work). Everything else is
    optional and lossy-tolerant, so you can paste an LLM's JSON output almost as-is:

      [
        {
          "title": "Earnings call: bull vs. bear",
          "prompt": "You are an equity analyst. Given {{transcript}} ...",
          "purpose": "Financial Analysis",        // optional use-case tag
          "model": "Claude",                       // optional target model
          "source": "https://reddit.com/...",      // optional provenance URL
          "category": "Finance",                   // optional
          "engagement": 120                         // optional real signal (upvotes/likes)
        }
      ]
    """
    def extract(self, config: Dict[str, Any]) -> List[PromptData]:
        here = os.path.dirname(os.path.abspath(__file__))
        default = os.path.join(here, "app", "backend", "sources", "llm_curated.json")
        path = config.get("path") or os.getenv("LLM_CURATED_PATH", default)
        platform = config.get("platform", "LLM-Curated")
        results: List[PromptData] = []
        if not os.path.exists(path):
            log.info("[%s] no file at %s (skipping)", platform, path)
            return results
        log.info("[%s] Reading pasted prompts from %s", platform, path)
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                items = json.load(f)
            if isinstance(items, dict):          # tolerate {"prompts": [...]} too
                items = items.get("prompts") or items.get("items") or []
            for it in items:
                if not isinstance(it, dict):
                    continue
                prompt = (it.get("prompt") or it.get("prompt_text") or it.get("text")
                          or it.get("template") or it.get("body") or "").strip()
                if not prompt:
                    continue
                title = (it.get("title") or it.get("name") or "Untitled").strip()[:80]
                eng = it.get("engagement") or it.get("upvotes") or it.get("likes") or 0
                try:
                    eng = int(eng)
                except (TypeError, ValueError):
                    eng = 0
                results.append(PromptData(
                    platform=platform,
                    title=title,
                    prompt_text=prompt,
                    model_target=str(it.get("model") or it.get("model_target") or "Any"),
                    category=str(it.get("category") or it.get("purpose") or "Other"),
                    url=str(it.get("source") or it.get("url") or ""),
                    engagement=eng,
                ))
            log.info("[%s] Loaded %d pasted prompts", platform, len(results))
        except Exception as e:
            log.warning("[%s] %s", platform, e)
        return results


# ==========================================
# 4. FACTORY & ROUTER
# ==========================================
class ScraperFactory:
    """Factory to instantiate the correct scraper based on target type."""

    _REGISTRY = {
        "API": APIScraper,
        "STATIC": StaticWebScraper,
        "HUGGINGFACE": HuggingFaceScraper,
        "MCP": MCPRegistryScraper,
        "HACKERNEWS": HackerNewsScraper,
        "GITHUB": GitHubScraper,
        "KAGGLE": KaggleScraper,
        "PROMPTHERO": PromptHeroScraper,
        "REDDIT": RedditScraper,
        "CANGHE": CangheGalleryScraper,
        "LLM_CURATED": LlmCuratedScraper,
    }

    @staticmethod
    def get_scraper(target_type: str, zenrows_manager: ZenRowsManager) -> ScraperStrategy:
        cls = ScraperFactory._REGISTRY.get(target_type)
        if cls is None:
            raise ValueError(f"Unknown target type: {target_type}")
        return cls(zenrows_manager)


# ==========================================
# 5. EVALUATION PIPELINE + EXPORT
# ==========================================
def export_to_excel(data: List[PromptData], filename: str = "extracted_prompts.xlsx",
                    keep_at: int = 70, review_at: int = 45, include_review: bool = True):
    """Run the multi-stage evaluation pipeline, then export best-first to Excel."""
    if not data:
        log.warning("No data to export.")
        return

    import pipeline
    rows = pipeline.evaluate_all(data, keep_at=keep_at, review_at=review_at)
    if not rows:
        log.warning("Nothing survived the pipeline.")
        return

    df = pd.DataFrame(rows)

    # Keep KEEP (+ optionally REVIEW); DROP rows are excluded from the library sheet.
    counts = df["decision"].value_counts().to_dict()
    log.info("Decisions: %s", counts)
    wanted = ["KEEP", "REVIEW"] if include_review else ["KEEP"]
    df = df[df["decision"].isin(wanted)]

    # Normalize smart quotes / dashes / ellipses to ASCII across all text columns.
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].map(normalize_text)

    df = df.sort_values("final_score", ascending=False).reset_index(drop=True)

    try:
        df.to_excel(filename, index=False)
        log.info("Exported %d prompts to %s (KEEP+REVIEW), best-first.", len(df), filename)
    except PermissionError:
        # Target is locked (open in Excel / OneDrive sync). Never lose the results —
        # write a timestamped fallback next to it.
        import time as _t
        base, ext = os.path.splitext(filename)
        fallback = f"{base}_{_t.strftime('%Y%m%d_%H%M%S')}{ext}"
        try:
            df.to_excel(fallback, index=False)
            log.warning("%s is locked (close it in Excel/OneDrive). Wrote results to %s instead.",
                        filename, fallback)
        except Exception as e:
            csv = base + ".csv"
            df.to_csv(csv, index=False)
            log.warning("Could not write xlsx (%s). Wrote CSV fallback to %s.", e, csv)
    except Exception as e:
        log.error("Error exporting to Excel: %s", e)


# ==========================================
# MAIN EXECUTION AGENT
# ==========================================
def run_target(target: Dict[str, Any], zenrows_manager: ZenRowsManager) -> List[PromptData]:
    target_type = target["target_type"]
    scraper = ScraperFactory.get_scraper(target_type, zenrows_manager)
    log.info("--- Routing to %s scraper for %s ---", target_type, target["platform_name"])
    items = scraper.extract(target)
    log.info("Extracted %d items from %s", len(items), target["platform_name"])
    return items


def build_targets() -> List[Dict[str, Any]]:
    """The full source list — shared by the batch scraper and the incremental refresh."""
    github_token = os.getenv("GITHUB_TOKEN", "YOUR_GITHUB_TOKEN")
    return [
        # --- HUGGING FACE (keyless, permissive-license datasets) ---
        {
            "target_type": "HUGGINGFACE",
            "platform_name": "HF: prompts.chat",
            "dataset": "fka/prompts.chat",
            "category": "ChatGPT/Utility", "model_target": "ChatGPT",
        },
        {
            "target_type": "HUGGINGFACE",
            "platform_name": "HF: Stable-Diffusion-Prompts",
            "dataset": "Gustavosta/Stable-Diffusion-Prompts", "max_rows": 400,
            "category": "Image Generation", "model_target": "Stable Diffusion",
        },
        {
            "target_type": "HUGGINGFACE",
            "platform_name": "HF: Midjourney-Prompts",
            "dataset": "succinctly/midjourney-prompts", "max_rows": 400,
            "category": "Image Generation", "model_target": "Midjourney",
        },
        {
            "target_type": "HUGGINGFACE",
            "platform_name": "HF: Midjourney-Detailed",
            "dataset": "MohamedRashad/midjourney-detailed-prompts", "max_rows": 200,
            "category": "Image Generation", "model_target": "Midjourney",
        },
        {
            "target_type": "HUGGINGFACE",
            "platform_name": "HF: SDXL Prompts",
            "dataset": "Falah/image_generation_prompts_SDXL", "max_rows": 200,
            "category": "Image Generation", "model_target": "SDXL",
        },
        # --- NEW: professional / instruction prompts (free, permissive licenses) ---
        {
            "target_type": "HUGGINGFACE",
            "platform_name": "HF: Dolly-15k (human instructions)",
            "dataset": "databricks/databricks-dolly-15k", "max_rows": 400,
            "category": "General/Instruction", "model_target": "General",
        },
        {
            "target_type": "HUGGINGFACE",
            "platform_name": "HF: No-Robots (human-written)",
            "dataset": "HuggingFaceH4/no_robots", "max_rows": 400,
            "category": "General/Instruction", "model_target": "General",
        },
        {
            "target_type": "HUGGINGFACE",
            "platform_name": "HF: Python Code Instructions",
            "dataset": "iamtarun/python_code_instructions_18k_alpaca", "max_rows": 300,
            "category": "Coding", "model_target": "General",
        },
        {
            "target_type": "HUGGINGFACE",
            "platform_name": "HF: HelpSteer (quality-rated)",
            "dataset": "nvidia/HelpSteer", "max_rows": 300,
            "category": "General/Instruction", "model_target": "General",
        },
        {
            "target_type": "HUGGINGFACE",
            "platform_name": "HF: SD-Prompts (daspartho)",
            "dataset": "daspartho/stable-diffusion-prompts", "max_rows": 300,
            "category": "Image Generation", "model_target": "Stable Diffusion",
        },
        {
            "target_type": "CANGHE",
            "platform_name": "GPT-Image2 Gallery (canghe.ai)",
        },
        # --- LLM-CURATED (prompts you sourced via Claude/ChatGPT/Gemini) ---
        {
            "target_type": "LLM_CURATED",
            "platform_name": "LLM-Curated (Claude/ChatGPT/Gemini)",
        },
        # --- UPLOADED (Excel/CSV you uploaded through the app; re-graded by the LLM here) ---
        {
            "target_type": "LLM_CURATED",
            "platform_name": "Uploaded (manual Excel/CSV)",
            "platform": "Uploaded",
            "path": os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "app", "backend", "sources", "uploaded.json"),
        },
        # --- CURATED / VENDOR (via GitHub API) ---
        {
            "target_type": "GITHUB",
            "platform_name": "GitHub: MIT prompt repos",
            "github_token": github_token,
            "query": "chatgpt+prompt+license:mit",
        },
        {
            "target_type": "GITHUB",
            "platform_name": "GitHub: prompt-engineering guides",
            "github_token": github_token,
            "query": "prompt-engineering+awesome+stars:>500",
        },
        # --- TIER A MARKETPLACE (ZenRows scrape) ---
        {
            "target_type": "PROMPTHERO",
            "platform_name": "PromptHero (ChatGPT)",
            "listing": "chatgpt-prompts", "category": "ChatGPT",
            "model_target": "ChatGPT",
        },
        {
            "target_type": "PROMPTHERO",
            "platform_name": "PromptHero (Midjourney)",
            "listing": "midjourney-prompts", "category": "Image Generation",
            "model_target": "Midjourney",
        },
        # --- REDDIT (official API — needs REDDIT_CLIENT_ID / _SECRET) ---
        {
            "target_type": "REDDIT",
            "platform_name": "Reddit (prompt subreddits)",
            "reddit_client_id": os.getenv("REDDIT_CLIENT_ID", ""),
            "reddit_client_secret": os.getenv("REDDIT_CLIENT_SECRET", ""),
            "subreddits": ["PromptEngineering", "ChatGPTPromptGenius", "StableDiffusion"],
        },
        # --- OTHER APIs ---
        {
            "target_type": "MCP",
            "platform_name": "Model Context Protocol Registry",
        },
        {
            "target_type": "HACKERNEWS",
            "platform_name": "Hacker News Algolia Search",
        },
        {
            "target_type": "KAGGLE",
            "platform_name": "Kaggle CC Datasets",
            "kaggle_username": os.getenv("KAGGLE_USERNAME", "YOUR_KAGGLE_USERNAME"),
            "kaggle_key": os.getenv("KAGGLE_KEY", "YOUR_KAGGLE_KEY"),
        },
        {
            "target_type": "STATIC",
            "platform_name": "The Prompt Index",
            "url": "https://thepromptindex.com",
        },
    ]


def scrape_all() -> List[PromptData]:
    """Run every source in parallel and return the raw scraped prompts (no grading/export)."""
    zenrows_manager = ZenRowsManager(api_key=os.getenv("ZENROWS_API_KEY", ""))
    targets = build_targets()
    data: List[PromptData] = []
    log.info("Scraping %d sources in parallel...", len(targets))
    with ThreadPoolExecutor(max_workers=len(targets)) as executor:
        futures = {executor.submit(run_target, t, zenrows_manager): t for t in targets}
        for future in as_completed(futures):
            t = futures[future]
            try:
                data.extend(future.result())
            except ValueError as ve:
                log.error("[Router] %s", ve)
            except Exception as e:
                log.error("[%s] Unhandled error: %s", t["platform_name"], e)
    return data


def main():
    data = scrape_all()
    keep_at = int(os.getenv("QUALITY_KEEP", "70"))
    review_at = int(os.getenv("QUALITY_REVIEW", "45"))
    out_xlsx = os.getenv("OUTPUT_XLSX", "legal_ai_prompts.xlsx")
    log.info("Extraction complete. Total records: %d. Running evaluation pipeline...", len(data))
    export_to_excel(data, out_xlsx, keep_at=keep_at, review_at=review_at)


if __name__ == "__main__":
    main()

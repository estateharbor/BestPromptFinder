"""
Prompt Finder API — serves the pipeline-evaluated corpus as a recommendation engine.

Endpoints
  GET  /api/health              -> status + corpus size
  POST /api/search {query}      -> parsed intent + ranked results (Quality/Match/Reliability/Overall)
  GET  /api/prompt/{id}         -> full prompt detail
  GET  /api/leaderboard         -> top performers by reliability

Run:  uvicorn api:app --reload --port 8000   (from app/backend)
Build corpus first: python build_corpus.py
"""
import os
from typing import Optional

# Load the repo-root .env (ANTHROPIC_API_KEY, LLM_MODEL, ...) if python-dotenv is present,
# so the LLM search enricher activates from the same .env the pipeline uses.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
except Exception:
    pass

from fastapi import FastAPI, HTTPException, Depends, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import JSONResponse

from matcher import Recommender
import store
import auth
from db import User

# Corpus path is configurable so the nightly pipeline can write a fresh one to a shared
# volume (CORPUS_PATH=/data/corpus.json) that this API auto-reloads. In Docker the entry
# point seeds that file from the image's baked copy on first start.
CORPUS = os.getenv("CORPUS_PATH", os.path.join(os.path.dirname(__file__), "corpus.json"))
store.init()

# Comma-separated allowed origins (set CORS_ORIGINS in prod, e.g. https://app.example.com)
_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")

# Admin accounts allowed to upload/ingest prompts (comma-separated emails in .env).
# Fail-closed: if unset, NOBODY is admin and the Upload button/endpoint stay locked.
_INGEST_ADMINS = {e.strip().lower() for e in os.getenv("INGEST_ADMINS", "").split(",") if e.strip()}


def _is_admin(email: str) -> bool:
    return bool(_INGEST_ADMINS) and (email or "").lower() in _INGEST_ADMINS

app = FastAPI(title="BestPromptFinder API", version="1.2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting — per client IP. Defaults to in-memory (per-instance); point
# RATELIMIT_STORAGE_URI at redis://... to share limits across backend replicas.
# When behind a reverse proxy (nginx/Caddy), the real client IP comes from
# X-Forwarded-For; slowapi's get_remote_address reads it when trusted.
limiter = Limiter(key_func=get_remote_address, storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"))
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
def _ratelimit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Too many requests — please slow down and try again shortly."})

_rec: Optional[Recommender] = None
_rec_mtime: float = 0.0


def rec() -> Recommender:
    """Return the recommender, auto-reloading when the corpus file changes on disk
    (so the nightly pipeline's fresh prompts go live without restarting the server)."""
    global _rec, _rec_mtime
    if not os.path.exists(CORPUS):
        if _rec is not None:
            return _rec  # keep serving the last-loaded corpus if the file vanishes mid-write
        raise HTTPException(503, "Corpus not built. Run: python build_corpus.py")
    mtime = os.path.getmtime(CORPUS)
    if _rec is None or mtime > _rec_mtime:
        _rec = Recommender(CORPUS, store=store)
        _rec_mtime = mtime
    return _rec


class SearchBody(BaseModel):
    query: str
    k: int = 4


class PreviewBody(BaseModel):
    id: Optional[str] = None
    prompt: Optional[str] = None


class VoteBody(BaseModel):
    id: str
    verdict: str  # 'worked' | 'didnt'
    model: str = ""


class AuthBody(BaseModel):
    email: str
    password: str


class SaveBody(BaseModel):
    id: str
    note: str = ""


@app.get("/api/health")
def health():
    ok = os.path.exists(CORPUS)
    return {"status": "ok" if ok else "no-corpus", "corpus_size": len(rec().corpus) if ok else 0}


@app.post("/api/search")
def search(body: SearchBody):
    q = (body.query or "").strip()
    if not q:
        raise HTTPException(400, "Empty query.")
    return rec().search(q, k=max(1, min(10, body.k)))


@app.get("/api/prompt/{pid}")
def prompt(pid: str):
    r = rec().get(pid)
    if not r:
        raise HTTPException(404, "Prompt not found.")
    return r


@app.get("/api/leaderboard")
def leaderboard(k: int = 6):
    return {"results": rec().leaderboard(k=max(1, min(12, k)))}


@app.get("/api/stats")
def stats():
    from datetime import datetime, timezone
    s = rec().stats()
    s["last_refreshed"] = (
        datetime.fromtimestamp(os.path.getmtime(CORPUS), tz=timezone.utc).isoformat()
        if os.path.exists(CORPUS) else None
    )
    try:
        allv = store.stats_all()
        s["votes"] = sum(v.get("worked", 0) + v.get("didnt", 0) for v in allv.values())
    except Exception:
        s["votes"] = 0
    return s


@app.post("/api/vote")
@limiter.limit("60/minute")
def vote(body: VoteBody, request: Request, user: User | None = Depends(auth.optional_user)):
    if body.verdict not in ("worked", "didnt"):
        raise HTTPException(400, "verdict must be 'worked' or 'didnt'.")
    r = rec()
    if body.id not in r._by_id:
        raise HTTPException(404, "Prompt not found.")
    store.add_vote(body.id, body.verdict, body.model, user_id=user.id if user else None)
    # Return the freshly recomputed reliability in the same shape the UI uses elsewhere.
    e = r._eff_rel(r._by_id[body.id])
    return {
        "ok": True,
        "reliability": {
            "uses": e["uses"], "useful": e["useful"], "tested": e["tested"],
            "last_verified": e["last_verified"], "score": e["reliability"],
            "worked": e["worked"], "didnt": e["didnt"], "votes": e["votes"], "source": e["source"],
        },
    }


@app.get("/api/preview/status")
def preview_status():
    import llm_preview
    return {"available": llm_preview.available()}


@app.post("/api/preview")
def preview(body: PreviewBody):
    import llm_preview
    if not llm_preview.available():
        raise HTTPException(503, "Live preview needs an Anthropic API key. Set ANTHROPIC_API_KEY in .env.")
    text = body.prompt
    if body.id:
        c = rec()._by_id.get(body.id)
        if not c:
            raise HTTPException(404, "Prompt not found.")
        if c.get("prompt_type") == "image":
            raise HTTPException(400, "Image prompts can't be previewed live (needs an image model).")
        text = c["prompt"]
    if not text:
        raise HTTPException(400, "Nothing to preview.")
    try:
        return llm_preview.generate(text)
    except Exception as e:
        if "budget" in str(e).lower():
            raise HTTPException(429, str(e))
        raise HTTPException(502, f"Preview failed: {e}")


# ---------------- auth ----------------
def _auth_response(user: User):
    return {"token": auth.create_token(user.id),
            "user": {"id": user.id, "email": user.email, "is_admin": _is_admin(user.email)}}


@app.post("/api/auth/register")
@limiter.limit("5/minute")
def register(body: AuthBody, request: Request):
    return _auth_response(auth.register(body.email, body.password))


@app.post("/api/auth/login")
@limiter.limit("10/minute")
def login(body: AuthBody, request: Request):
    return _auth_response(auth.login(body.email, body.password))


@app.get("/api/me")
def me(user: User = Depends(auth.current_user)):
    return {"id": user.id, "email": user.email, "is_admin": _is_admin(user.email)}


@app.get("/api/admin/activity")
def admin_activity(user: User = Depends(auth.current_user)):
    """Admin-only: daily 'prompts pulled / AI-graded' report from the refresh log."""
    if not _is_admin(user.email):
        raise HTTPException(403, "Admins only.")
    import json as _json
    path = os.path.join(os.path.dirname(CORPUS) or ".", "activity.json")
    data = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
        except Exception:
            data = {}
    days = [{"date": k, **v} for k, v in sorted(data.items(), reverse=True)][:30]
    from datetime import datetime, timezone
    last = (datetime.fromtimestamp(os.path.getmtime(CORPUS), tz=timezone.utc).isoformat()
            if os.path.exists(CORPUS) else None)
    return {"days": days, "last_refreshed": last}


# ---------------- per-user library ----------------
@app.get("/api/library")
def library(user: User = Depends(auth.current_user)):
    r = rec()
    ids = store.library_ids(user.id)
    items = [r.get(pid) for pid in ids if pid in r._by_id]
    return {"count": len(items), "results": items}


@app.get("/api/library/ids")
def library_ids(user: User = Depends(auth.current_user)):
    return {"ids": store.library_ids(user.id)}


@app.post("/api/library")
def save(body: SaveBody, user: User = Depends(auth.current_user)):
    if body.id not in rec()._by_id:
        raise HTTPException(404, "Prompt not found.")
    added = store.save_prompt(user.id, body.id, body.note)
    return {"saved": True, "already": not added}


@app.delete("/api/library/{pid}")
def unsave(pid: str, user: User = Depends(auth.current_user)):
    store.unsave_prompt(user.id, pid)
    return {"saved": False}


# ---------------- manual ingestion (upload an Excel/CSV of prompts) ----------------
@app.post("/api/ingest")
@limiter.limit("6/minute")
async def ingest(request: Request, file: UploadFile = File(...),
                 user: User = Depends(auth.current_user)):
    """Upload an .xlsx/.csv of prompts; they're graded, deduped, and added to the library.

    Admin-only: the uploader's email must be in INGEST_ADMINS (fail-closed if unset)."""
    if not _is_admin(user.email):
        raise HTTPException(403, "Only admin accounts can upload prompts.")
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(400, "Please upload an .xlsx, .xls, or .csv file.")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 8 MB).")
    import ingest as ingest_mod
    try:
        summary = ingest_mod.ingest_bytes(data, file.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))
    rec()  # force a corpus reload so the new prompts are immediately searchable
    return summary

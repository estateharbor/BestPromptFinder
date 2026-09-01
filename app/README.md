# Prompt Finder — full stack

An intent-first prompt **recommendation engine**. Describe a goal in plain words; the
app parses intent, scores every candidate on **Quality · Match · Reliability**, ranks
them, and explains *why* — all served from the evaluation pipeline's output.

```
Vite/React/TS/Tailwind  ──/api──▶  FastAPI  ──▶  matcher  ──▶  corpus.json
   (app/frontend)          proxy    (app/backend)   (intent→match→rank)   ▲
                                                                          │
                                          built by build_corpus.py from  ─┘
                                          ../legal_ai_prompts.xlsx  (pipeline output)
```

## How it's wired to the pipeline
1. `scraper_agent.py` (repo root) runs the scrape + evaluation pipeline → `legal_ai_prompts.xlsx`.
2. `backend/build_corpus.py` turns that output (plus a small curated seed pack) into `corpus.json`.
3. `backend/matcher.py` reuses the pipeline's purpose taxonomy, builds a TF-IDF index over the
   corpus, and computes **Match** + the **Overall** ranking (Quality .35 + Match .40 + Reliability .20 + Freshness .05).
4. `backend/api.py` (FastAPI) serves `/api/search`, `/api/prompt/{id}`, `/api/leaderboard`.
5. The React front end calls those endpoints (Vite proxies `/api` → `:8000`).

## Run it

**1 — Backend** (from `app/backend`)
```bash
pip install -r requirements.txt
python build_corpus.py            # reads ../../legal_ai_prompts.xlsx -> corpus.json
uvicorn api:app --reload --port 8000
```

**2 — Frontend** (from `app/frontend`, in a second terminal)
```bash
npm install
npm run dev                       # http://localhost:5173
```

Open http://localhost:5173 and search, or click an example / a leaderboard row.
The backend uses SQLite locally (`promptfinder.db`) unless `DATABASE_URL` is set.

## Deploy (Docker + Postgres)

Everything is containerized; votes and user libraries live in Postgres (the `pgdata`
volume), so they **persist across restarts and are shared by every backend instance**.

```bash
cd app
cp .env.example .env      # set POSTGRES_PASSWORD, JWT_SECRET (and ANTHROPIC_API_KEY to enable LLM)
docker compose up --build
# open http://localhost:8080
```

- **db** — Postgres 16 (named volume `pgdata`)
- **backend** — FastAPI (built from the repo root so it can bake the corpus); `DATABASE_URL`
  points at Postgres, tables auto-create on startup
- **frontend** — the SPA built and served by nginx, which proxies `/api` to the backend
  (same-origin, so no CORS in prod)

To scale the API, run more `backend` replicas against the same Postgres — state is shared.

### HTTPS in production (Caddy)

`docker-compose.prod.yml` adds a **Caddy** reverse proxy that terminates TLS with an
**automatic Let's Encrypt certificate** — no manual cert steps.

```bash
cd app
cp .env.example .env       # set DOMAIN (a real, DNS-pointed domain), plus the secrets
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
# https://your-domain  (Caddy provisions the cert on first request)
```

Point your domain's DNS at the host and set `DOMAIN`; `DOMAIN=localhost` serves an HTTPS
test cert via Caddy's local CA. The overlay also stops publishing the SPA port directly —
the only public entry points become Caddy's 80/443.

### Rate limiting

Auth and vote endpoints are rate-limited per client IP (`slowapi`):
`register 5/min`, `login 10/min`, `vote 60/min` → excess returns **429**. The API runs
with `--proxy-headers --forwarded-allow-ips=*` so the **real** client IP (from
`X-Forwarded-For`) is used behind the proxy. Limits are in-memory per instance by default;
set `RATELIMIT_STORAGE_URI=redis://…` to share them across replicas.

## API
| Method | Route | Purpose |
|--------|-------|---------|
| GET  | `/api/health` | status + corpus size |
| POST | `/api/search` `{query, k}` | parsed intent + ranked results |
| GET  | `/api/prompt/{id}` | full prompt detail |
| GET  | `/api/leaderboard?k=` | top performers by reliability |
| POST | `/api/vote` `{id, verdict}` | record a worked/didn't-work outcome |
| POST | `/api/preview` `{id}` | live model-run sample output (needs key) |
| POST | `/api/auth/register` · `/api/auth/login` `{email, password}` | returns a JWT |
| GET  | `/api/me` | current user (auth) |
| GET/POST/DELETE | `/api/library[/{id}]` | list / save / unsave (auth) |

## Auth & private libraries (built)
- Email/password accounts with **bcrypt-hashed** passwords and **JWT** sessions (`auth.py`);
  the token is stored client-side and restores the session on reload.
- Each user has a **private library** — the ☆/★ button on any result saves it (`saved_prompts`
  table, unique per user+prompt); "My library" lists them. Votes also attach the voter's id.
- Data model lives in `db.py` (SQLAlchemy): `users`, `votes`, `saved_prompts` — same schema on
  SQLite and Postgres.

## Honest notes
- **Reliability flywheel (built).** Each result has a "Did it work?" 👍/👎 control that posts
  to `POST /api/vote`; votes persist in SQLite (`store.py`, `votes.db`). The Reliability score
  is then recomputed from **real votes blended with the seeded prior** (a pseudo-count prior so
  a single vote doesn't swing it, and a confidence term that ramps with volume) — see
  `matcher._eff_rel`. Search ranking, the leaderboard, and each result reflect live votes; the
  UI shows "verified by N votes (X% useful)" vs "seeded estimate". Uses/tested/last-verified
  start as seeded sample data (`build_corpus.py::seed_reliability`) and are labeled as such.
- **LLM search enricher (built).** `/api/search` retrieves with TF-IDF, then — when an
  Anthropic key is present — asks Claude to judge each shortlisted prompt against the user's
  *specific goal*, producing a real **Purpose-Match** score plus goal-tailored **why** bullets
  and a **weakness**; results re-rank on that match. Enable it by setting `ANTHROPIC_API_KEY`
  (and optionally `LLM_MODEL`, default `claude-sonnet-5`) in the repo-root `.env`; the backend
  loads it automatically. Without a key it falls back to the deterministic match + synthesized
  explanations. Each result carries `match_source: "llm" | "heuristic"`, and the response a
  top-level `enriched` flag (the UI shows an "AI-matched" badge). Toggle off with `SEARCH_USE_LLM=0`.
- The **curated seed pack** (`curated_seed.json`) adds ~10 strong prompts so common
  professional jobs (finance, marketing, image) have good coverage alongside the scraped corpus.
- **Live sample previews (built).** In a text/coding/data result, "Preview live output"
  calls `POST /api/preview` which runs the prompt through Claude and returns a short,
  representative example of what it produces (`llm_preview.py`). Needs `ANTHROPIC_API_KEY`;
  without one the button shows a graceful "add a key" hint (`GET /api/preview/status` reports
  availability). Image prompts keep the representative tile — Anthropic doesn't generate images.

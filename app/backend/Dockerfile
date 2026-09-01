# Prompt Finder API — build context is the REPO ROOT (so it can grab the pipeline
# output + modules). Build from app/ via docker-compose, or:
#   docker build -f app/backend/Dockerfile -t promptfinder-api .
FROM python:3.12-slim

WORKDIR /srv/app/backend

# Python deps first (better layer caching)
COPY app/backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Repo-root modules the backend imports at runtime (pipeline = purpose classification
# + heuristic grading on upload; budget = the daily LLM spend guard). ingest.py adds
# /srv to sys.path so these resolve.
COPY pipeline.py /srv/pipeline.py
COPY budget.py /srv/budget.py

# Backend source — includes the committed corpus.json (the library the API serves).
COPY app/backend/ /srv/app/backend/

ENV PORT=8000
EXPOSE 8000
# On first start, seed the shared corpus (CORPUS_PATH) from the image's baked copy so the
# app works before the first nightly refresh; thereafter the API auto-reloads that file.
# --proxy-headers + --forwarded-allow-ips=* so the real client IP (from the reverse proxy's
# X-Forwarded-For) drives rate limiting. Safe here: the API is only reachable via the proxy.
CMD ["sh", "-c", "if [ -n \"$CORPUS_PATH\" ] && [ ! -f \"$CORPUS_PATH\" ]; then mkdir -p \"$(dirname \"$CORPUS_PATH\")\" && cp corpus.json \"$CORPUS_PATH\"; fi; uvicorn api:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips=*"]

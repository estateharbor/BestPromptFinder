# Prompt Finder nightly pipeline (worker) — build context is the REPO ROOT.
# Runs the full collect -> clean -> grade -> rebuild-corpus job, writing to /data.
#   docker build -f app/pipeline.Dockerfile -t promptfinder-pipeline .
FROM python:3.12-slim

WORKDIR /app

# Scraper + pipeline deps (root requirements)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Pipeline modules
COPY scraper_agent.py pipeline.py semantic.py templates.py llm_evaluator.py budget.py refresh_smart.py ./
# Library policy files read by pipeline.content_violation / is_blocked (same relative path as
# in the repo, so <dir of pipeline.py>/app/backend/sources/... resolves).
COPY app/backend/sources/blocked_names.txt app/backend/sources/blocked_keys.txt ./app/backend/sources/
# Corpus builder + curated seed
COPY app/backend/build_corpus.py app/backend/curated_seed.json ./backend/
# The refresh entrypoint
COPY app/refresh.sh ./refresh.sh
RUN chmod +x refresh.sh

CMD ["./refresh.sh"]

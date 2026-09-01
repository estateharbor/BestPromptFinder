# Prompt Finder nightly pipeline (worker) — build context is the REPO ROOT.
# Runs the full collect -> clean -> grade -> rebuild-corpus job, writing to /data.
#   docker build -f app/pipeline.Dockerfile -t promptfinder-pipeline .
FROM python:3.12-slim

WORKDIR /app

# Scraper + pipeline deps (root requirements)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Pipeline modules
COPY scraper_agent.py pipeline.py semantic.py templates.py llm_evaluator.py budget.py ./
# Corpus builder + curated seed
COPY app/backend/build_corpus.py app/backend/curated_seed.json ./backend/
# The refresh entrypoint
COPY app/refresh.sh ./refresh.sh
RUN chmod +x refresh.sh

CMD ["./refresh.sh"]

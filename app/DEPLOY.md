# Deploy Prompt Finder on a Hostinger VPS (auto-refreshing)

This runs the whole app on an always-on server and **refreshes the prompt library every
night by itself** — collect new prompts → clean → AI-grade (capped at $1/day) → the live
site picks them up automatically, no restart.

```
                       ┌─────────── VPS (always on) ───────────┐
  visitors ─HTTPS─▶ Caddy ─▶ nginx (SPA + /api) ─▶ FastAPI ─▶ Postgres
                                                      ▲  reads
                                                 /data/corpus.json  ◀── nightly `pipeline`
                                                 (shared volume)         worker (cron)
```

## 1. Point a domain at the VPS
In your DNS (Hostinger → Domains → DNS), add an **A record** for your domain (or a
subdomain like `app.yourdomain.com`) pointing to the VPS's IP address.

## 2. Prepare the VPS (one time)
SSH in (Hostinger gives you the IP + root password), then install Docker:

```bash
curl -fsSL https://get.docker.com | sh
```

Upload the project (from your PC, in the repo folder):

```bash
# either git clone your repo, or copy the folder up with scp:
scp -r "Fresh Prompt" root@YOUR_VPS_IP:/root/promptfinder
```

## 3. Configure secrets
```bash
cd /root/promptfinder/app
cp .env.example .env
nano .env      # set these:
```
- `DOMAIN` = your domain (for automatic HTTPS)
- `POSTGRES_PASSWORD`, `JWT_SECRET` = long random strings
- `ANTHROPIC_API_KEY` = your key (enables AI grading + search + previews)
- `DAILY_BUDGET_USD` = `1.0` (the nightly grading stays under this)
- Optional source keys (`ZENROWS_API_KEY`, `GITHUB_TOKEN`, `KAGGLE_*`, `REDDIT_*`) — sources without a key just skip.

## 4. Start the app (with HTTPS)
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```
Visit `https://your-domain` — the app is live (serving the corpus baked into the image).

## 5. Run the first refresh, then schedule it nightly
Run it once to build a fresh library:
```bash
docker compose run --rm pipeline
```
The API auto-reloads `/data/corpus.json` within a request — no restart needed.

Schedule it every night at 2 AM with the VPS crontab:
```bash
crontab -e
```
Add this line (adjust the path):
```
0 2 * * * cd /root/promptfinder/app && docker compose run --rm pipeline >> /var/log/pf-refresh.log 2>&1
```
Done. Every night the worker collects new prompts, grades them within the $1 cap, and the
live site serves them automatically the next morning.

## How the budget behaves nightly
The grader uses the **Batch API (50% off)** and a **pre-submission guard**: it only grades
as many prompts as fit `DAILY_BUDGET_USD`; the rest keep their heuristic score and get
graded on a following night. A full corpus grades for ~$0.89 — inside a $1 cap.

## Useful commands
```bash
docker compose logs -f backend           # app logs
docker compose run --rm pipeline         # refresh now
cat /var/log/pf-refresh.log              # nightly refresh history
docker compose -f docker-compose.yml -f docker-compose.prod.yml down   # stop
```

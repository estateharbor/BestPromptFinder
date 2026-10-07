#!/bin/sh
# Hourly auto-publish (VPS cron): pull new commits; if anything changed, rebuild the app,
# then import every daily prompt CSV that hasn't been imported yet. Idempotent and safe to
# re-run: ingest.py skips duplicates and enforces the content policy + licence gate.
#
# Install once (as root on the VPS):
#   chmod +x /root/promptfinder/app/daily_import.sh
#   (crontab -l 2>/dev/null; echo "15 * * * * /root/promptfinder/app/daily_import.sh >> /root/daily_import.log 2>&1") | crontab -
set -e
REPO=/root/promptfinder
DONE="$REPO/.daily_imported"           # list of CSVs already imported (outside git)
DC="docker compose -f docker-compose.yml -f docker-compose.hostnginx.yml"
cd "$REPO"
touch "$DONE"

before=$(git rev-parse HEAD)
git pull -q --ff-only || { echo "$(date -u) git pull failed"; exit 1; }
after=$(git rev-parse HEAD)

cd "$REPO/app"
if [ "$before" != "$after" ]; then
  echo "$(date -u) new commits $before..$after, rebuilding"
  $DC up --build -d
  $DC build pipeline >/dev/null
  sleep 8
fi

for f in $(ls backend/sources/daily/curated_*.csv 2>/dev/null | sort); do
  name=$(basename "$f")
  grep -qx "$name" "$DONE" && continue
  echo "$(date -u) importing $name"
  if $DC exec -T backend python ingest.py "sources/daily/$name"; then
    echo "$name" >> "$DONE"
  else
    echo "$(date -u) import of $name failed; will retry next hour"
  fi
done

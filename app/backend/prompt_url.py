"""
Print the live URL each row of a curated CSV will get once imported.

Uses the same id rule as ingest.py (md5 of title + first 40 normalized chars) and the same
slug rule as seo.prompt_path, so promotion drafts can link to a prompt before it is live.

  python prompt_url.py sources/daily/curated_2026-10-08.csv
"""
import csv
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
sys.path.insert(0, HERE)
import pipeline  # noqa: E402
import seo  # noqa: E402

SITE = "https://bestpromptfinder.com"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def url_for(title: str, prompt: str) -> str:
    cleaned, _ = pipeline.normalize_prompt(prompt)
    title = (title or cleaned[:60]).strip()[:80]
    pid = "p_" + hashlib.md5((title + cleaned[:40]).encode()).hexdigest()[:10]
    return SITE + seo.prompt_path({"title": title, "id": pid})


if __name__ == "__main__":
    for path in sys.argv[1:]:
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                print(f"{row['title']}\t{url_for(row['title'], row['prompt'])}")

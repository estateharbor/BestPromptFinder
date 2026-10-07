"""
List this week's top posts from the AI subreddits the trend scout watches.

Reads Reddit's public Atom feeds (/r/<sub>/top/.rss?t=week); the JSON API returns 403
without OAuth. Read-only, one request per subreddit with a pause between them.

  python reddit_top.py                      # default subreddits, top 10 each, past week
  python reddit_top.py --t day --limit 15 GeminiAI aivideo
"""
import argparse
import html
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

DEFAULT_SUBS = [
    "ChatGPT", "OpenAI", "ClaudeAI", "GeminiAI", "midjourney", "StableDiffusion",
    "PromptEngineering", "aivideo", "ChatGPTPromptGenius", "nanobanana", "IndiaTech",
]
UA = "BestPromptFinder-trend-scout/1.0 (read-only daily trend scan)"
NS = {"a": "http://www.w3.org/2005/Atom"}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def fetch(sub, t, limit):
    url = f"https://www.reddit.com/r/{sub}/top/.rss?t={t}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for wait in (15, 45, None):  # Reddit rate-limits anonymous feeds; back off on 429
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                root = ET.fromstring(r.read())
            break
        except urllib.error.HTTPError as ex:
            if ex.code != 429 or wait is None:
                raise
            time.sleep(wait)
    posts = []
    for e in root.findall("a:entry", NS):
        body = html.unescape(re.sub(r"<[^>]+>", " ", e.findtext("a:content", "", NS)))
        body = re.sub(r"\s+", " ", body).replace("submitted by", "|").split("|")[0].strip()
        posts.append({
            "title": e.findtext("a:title", "", NS),
            "url": e.find("a:link", NS).get("href"),
            "date": e.findtext("a:published", e.findtext("a:updated", "", NS), NS)[:10],
            "snippet": body[:220],
        })
    return posts


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("subs", nargs="*", default=DEFAULT_SUBS)
    ap.add_argument("--t", default="week", choices=["day", "week", "month"])
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    for i, sub in enumerate(a.subs):
        if i:
            time.sleep(6)
        print(f"\n## r/{sub} (top, {a.t})")
        try:
            for p in fetch(sub, a.t, a.limit):
                print(f"- [{p['date']}] {p['title']}\n  {p['url']}")
                if p["snippet"]:
                    print(f"  > {p['snippet']}")
        except Exception as ex:
            print(f"  (failed: {ex})")

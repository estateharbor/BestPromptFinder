---
name: prompt-audit
description: Audit BestPromptFinder library prompts that no audit has covered yet (new scrapes, uploads, curated CSVs) — check licence, content policy, language and quality, rewrite or remove where required, validate, and apply. Use when the user asks to audit, review or clean new prompts, or before importing a new prompt CSV.
argument-hint: "[path to new-prompts CSV, or empty to export from the live library]"
---

# Prompt audit

Runs the same audit as the 2026-10-06 full-library review on prompts that aren't covered yet.
Every prompt ends up with exactly one decision: `remove`, `rewrite`, `licence` or `keep`.

Input: $ARGUMENTS

## 1. Get the unaudited prompts

- **CSV given** (a new batch before upload): audit those rows directly. Each row needs title,
  prompt text and source/licence.
- **Nothing given**: the live library is on the VPS, and Claude can't SSH there (password
  login). Ask the user to run this and save the output in the repo root:

  ```bash
  ssh root@82.112.237.153 "cd /root/promptfinder/app && docker compose -f docker-compose.yml -f docker-compose.hostnginx.yml exec -T backend python audit_new_prompts.py export" > new_prompts_audit.csv
  ```

  It lists every prompt that no `app/backend/sources/audit/*.csv` covers and that isn't already
  unpublished, with automatic `flags` and a `suggested_action`. Treat those as hints and review
  every row yourself.

## 2. Policy (apply in this order)

1. **Content policy → `remove`.** Sexual content; anything that could sexualise a minor (zero
   tolerance, including "girl/少女" in suggestive, selfie, bedroom, beach or bath framing); a
   real, identifiable person's likeness (politicians, celebrities, private people); jailbreaks,
   manipulation or detection-evasion; fake screenshots of real platforms (Douyin, TikTok,
   YouTube, WeChat…); prompts asking a model to invent testimonials, reviews or results.
   Never "rewrite" these into something milder: remove them. If you find a real person the
   rules missed, add the name to `app/backend/sources/blocked_names.txt`.
2. **Junk → `remove`.** Training-data rows ("Below is an instruction…"), dataset dumps,
   scraped comments, repo descriptions, near-duplicates, text that isn't a prompt.
3. **Licence.** A third-party prompt may be published as-is only when its licence explicitly
   covers the **prompt text**: CC0, MIT, Apache-2.0 or CC BY with credit. Not "images are CC0",
   and not a licence on surrounding code. Then use `licence` with the licence string, e.g.
   `CC0-1.0, prompts.chat`. Non-commercial (NC), share-alike (SA), unknown, none, "all rights
   reserved", social posts and vendor blogs all mean `rewrite` (or `remove` if it isn't worth
   keeping). Verify the licence at the source (dataset card, LICENSE file); don't trust a
   scraper's label. If a source keeps failing, switch it off in
   `scraper_agent.build_targets()` (`"license": None` plus the reason).
4. **Language.** The site is English. Non-English prompts get an English rewrite. If the
   *output* must be in another language (a Chinese textbook page), say so inside an English
   prompt.
5. **Our own editorial prompts** (no source URL) are `keep` unless they break 1–4. Style alone
   ("sounds AI-written") is not a reason to rewrite; only rewrite if the result is clearly
   better and loses none of the original's structure.

## 3. How to rewrite (the legal part matters)

Copyright protects wording, not ideas. A close paraphrase is still copying, so:

1. Write a one-line spec of the **idea only**: task, inputs, output, constraints.
2. Write the new prompt **from the spec, without looking at the original wording**. Use your
   own structure, bracketed placeholders (`[product]`, `[city]`), a clear output shape, and no
   invented facts (use `[VERIFY: …]` where facts are needed). Drop living artists' names and
   keyword soup ("8k, masterpiece, trending on artstation").
3. Give it a plain, descriptive English title (it becomes the URL slug; old URLs redirect).
4. The validator (step 4) must report under 10% shared 5-word runs. Subject nouns overlapping
   in short image prompts is normal; shared phrasing isn't.

## 4. Write, validate, apply

1. Save decisions as `app/backend/sources/audit/audit_<YYYY-MM-DD>.csv` with columns
   `id,decision,source,reasons,new_title,new_prompt,licence` (the same format as
   `audit_2026-10-06.csv`). Include **every** reviewed id, including `keep`, so it isn't
   exported again.
2. Validate against a copy of the live corpus, which the user can save with
   `... exec -T backend cat /data/corpus.json > live_corpus.json`:

   ```bash
   cd app/backend && CORPUS_PATH=../../live_corpus.json python audit_new_prompts.py check sources/audit/audit_<date>.csv
   ```

   Fix every reported problem and re-run until it shows 0.
3. For removed and rewritten prompts, add their text fingerprints to
   `sources/blocked_keys.txt`, so scrapers and uploads can't bring the originals back:
   `python -c "import pipeline; print(pipeline.blocked_key(open('x.txt',encoding='utf-8').read()))"`,
   or loop over the rows. Add removed ids to `corpus_overrides.json` → `remove`.
4. Dry run, then show the user the counts:
   `CORPUS_PATH=../../live_corpus.json AUDIT=sources/audit/audit_<date>.csv python apply_audit.py`
5. Commit and push. Then give the user one deploy command. It rebuilds, then dry-runs and
   applies on the VPS:

   ```bash
   ssh root@82.112.237.153 "cd /root/promptfinder && git pull && cd app && docker compose -f docker-compose.yml -f docker-compose.hostnginx.yml up --build -d && sleep 5 && docker compose -f docker-compose.yml -f docker-compose.hostnginx.yml exec -T -e AUDIT=sources/audit/audit_<date>.csv -e APPLY=1 backend python apply_audit.py"
   ```

6. After the user says it's done, spot-check on the live site: a removed id returns 404, a
   rewritten page shows "Created by BestPromptFinder", and a licence page shows its licence.

## Guardrails

- Present the remove list to the user before applying when it includes anything that isn't
  clearly junk or a content-policy hit.
- Never put removed prompts' text in the repo. Fingerprints and ids only. The audit CSV keeps
  rewrites, not originals.
- Rewritten prompts are re-graded automatically (eval_source "heuristic") and stay noindex
  until then. Don't inflate quality scores to get them indexed.
- Report counts honestly: removed / rewritten / licence recorded / kept / not found.

"""
The recommendation core: intent -> match -> rank.

Given a natural-language goal, this:
  1. Parses intent   (purpose classification + prompt-type + key tokens)
  2. Scores Match     (TF-IDF cosine between the goal and each prompt, + purpose alignment)
  3. Ranks            (Overall = Quality .35 + Match .40 + Reliability .20 + Freshness .05)
  4. Explains         (synthesizes "why" bullets + a weakness from the prompt's own attributes)

Quality, purpose, and templates come straight from the pipeline's corpus; Match and the
Overall ranking are computed here. Purpose classification reuses the pipeline's taxonomy
when importable, so the API and the offline pipeline agree on categories.
"""
import os
import re
import sys
import math
import json
from typing import List, Dict, Any

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Reuse the pipeline's purpose taxonomy (real wiring); fall back if unavailable.
try:
    from pipeline import classify_purpose, detect_type
except Exception:
    def classify_purpose(text, category=""):  # minimal fallback
        return ""
    def detect_type(text, category=""):
        return "text"

# Optional LLM enricher for real goal-specific Match + why/weakness.
try:
    import llm_enrich
except Exception:
    llm_enrich = None

RETRIEVE_N = 8  # TF-IDF shortlist size sent to the LLM judge before final ranking

_WORD = re.compile(r"[A-Za-z0-9]+")
_ROLE = re.compile(r"\b(you are|act as|your task|your job|as an? \w+ (analyst|expert|specialist))\b", re.I)
_FORMAT = re.compile(r"\b(step[- ]by[- ]step|table|json|list|bullet|\d+\s*(ideas|options|variations|posts)|--ar|format|schema|section)\b", re.I)
_CONSTRAINT = re.compile(r"(--\w+|\{[^}]+\}|\bexactly \d+|\bunder \d+|\bdo not\b|\btone\b|\baudience\b)", re.I)


class Recommender:
    def __init__(self, corpus_path: str, store=None):
        with open(corpus_path, "r", encoding="utf-8") as f:
            self.corpus: List[Dict[str, Any]] = json.load(f)
        self._by_id = {c["id"]: c for c in self.corpus}
        self.store = store  # optional outcome-vote store (Reliability flywheel)
        self._build_index()

    # ---- effective reliability: seed prior blended with real "worked/didn't" votes ----
    def _eff_rel(self, c: Dict[str, Any], votes: Dict[str, Dict[str, int]] = None) -> Dict[str, Any]:
        seed = c["reliability"]
        v = (votes or {}).get(c["id"]) if votes is not None else (self.store.stats(c["id"]) if self.store else None)
        worked = (v or {}).get("worked", 0)
        didnt = (v or {}).get("didnt", 0)
        total = worked + didnt
        if total > 0:
            K = 6  # pseudo-count: seed acts as a prior until real votes accumulate
            prior = seed["useful"] / 100.0
            useful = round(100 * (worked + prior * K) / (total + K))
            confidence = min(1.0, total / 20.0)          # ramps up as votes come in
            reliability = min(100, round(useful * 0.7 + confidence * 30))
            source = "votes"
        else:
            useful, reliability, source = seed["useful"], seed["reliability"], "seeded"
        return {
            "uses": seed["uses"], "useful": useful, "tested": seed["tested"],
            "last_verified": seed["last_verified"], "reliability": reliability,
            "worked": worked, "didnt": didnt, "votes": total, "source": source,
        }

    # ---- TF-IDF index over the corpus (fixed idf; queries project into it) ----
    def _build_index(self):
        docs = [self._tokens(c["prompt"] + " " + c["title"] + " " + c["purpose"]) for c in self.corpus]
        n = len(docs)
        df = {}
        for toks in docs:
            for w in set(toks):
                df[w] = df.get(w, 0) + 1
        self.idf = {w: math.log((1 + n) / (1 + c)) + 1.0 for w, c in df.items()}
        self.vecs = [self._vectorize(toks) for toks in docs]

    def _tokens(self, text: str) -> List[str]:
        return [w.lower() for w in _WORD.findall(text or "")]

    def _vectorize(self, toks: List[str]) -> Dict[str, float]:
        tf = {}
        for w in toks:
            tf[w] = tf.get(w, 0) + 1
        vec = {w: c * self.idf.get(w, 1.0) for w, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {w: v / norm for w, v in vec.items()}

    @staticmethod
    def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(k, 0.0) for k, v in a.items())

    # ---- intent ----
    def parse_intent(self, query: str) -> Dict[str, Any]:
        purpose = classify_purpose(query) or "General"
        ptype = detect_type(query)
        return {
            "purpose": purpose,
            "prompt_type": ptype,
            "query": query,
        }

    def _deterministic_match(self, c, sim, smax, intent) -> int:
        base = (sim / smax) if smax else 0.0
        match = base * 100.0
        if intent["purpose"] and c["purpose"] and intent["purpose"].lower() in c["purpose"].lower():
            match = min(100.0, match + 14)
        if c["prompt_type"] == intent["prompt_type"]:
            match = min(100.0, match + 4)
        return round(match)

    @staticmethod
    def _overall(quality, match, reliability, freshness=100) -> int:
        return round(quality * 0.35 + match * 0.40 + reliability * 0.20 + freshness * 0.05)

    # ---- match + rank (retrieve -> LLM enrich -> re-rank) ----
    def search(self, query: str, k: int = 4) -> Dict[str, Any]:
        intent = self.parse_intent(query)
        qvec = self._vectorize(self._tokens(query))
        sims = [self._cosine(qvec, v) for v in self.vecs]
        smax = (max(sims) if sims else 1.0) or 1.0

        votes = self.store.stats_all() if self.store else {}

        # 1) TF-IDF shortlist by deterministic overall (reliability reflects real votes)
        pre = []
        for c, sim in zip(self.corpus, sims):
            m = self._deterministic_match(c, sim, smax, intent)
            rel = self._eff_rel(c, votes)["reliability"]
            o = self._overall(c["quality"], m, rel)
            pre.append((o, m, c))
        pre.sort(key=lambda t: t[0], reverse=True)
        shortlist = pre[:RETRIEVE_N]

        # 2) LLM enrich the shortlist for real goal-specific match + why/weakness
        enrich = {}
        used_llm = False
        if llm_enrich and llm_enrich.available():
            cands = [{"id": c["id"], "title": c["title"], "prompt": c["prompt"]} for _, _, c in shortlist]
            enrich = llm_enrich.enrich(query, cands)
            used_llm = bool(enrich)

        # 3) Final ranking (LLM match overrides deterministic when present)
        ranked = []
        for det_overall, det_match, c in shortlist:
            e = enrich.get(c["id"])
            match = e["match"] if e else det_match
            rel = self._eff_rel(c, votes)["reliability"]
            overall = self._overall(c["quality"], match, rel)
            ranked.append((overall, match, c, e))
        ranked.sort(key=lambda t: t[0], reverse=True)

        results = [self._result(c, o, m, intent, llm=e, votes=votes) for o, m, c, e in ranked[:k]]
        return {"intent": intent, "count": len(self.corpus), "enriched": used_llm, "results": results}

    def get(self, pid: str) -> Dict[str, Any]:
        c = self._by_id.get(pid)
        if not c:
            return None
        return self._result(c, None, None, None)

    def stats(self) -> Dict[str, Any]:
        """Library overview — totals, per-source, per-purpose, and grading coverage."""
        from collections import Counter
        plat = Counter(c["platform"] for c in self.corpus)
        purp = Counter(c["purpose"] for c in self.corpus)
        typ = Counter(c["prompt_type"] for c in self.corpus)
        ev = Counter((c.get("provenance") or {}).get("eval_source", "heuristic") for c in self.corpus)
        return {
            "total": len(self.corpus),
            "by_platform": dict(plat.most_common()),
            "by_purpose": dict(purp.most_common(8)),
            "by_type": dict(typ.most_common()),
            "eval_source": dict(ev),
        }

    def leaderboard(self, k: int = 6) -> List[Dict[str, Any]]:
        votes = self.store.stats_all() if self.store else {}
        rows = [(self._eff_rel(c, votes), c) for c in self.corpus]
        rows.sort(key=lambda t: (t[0]["reliability"], t[0]["votes"], t[0]["uses"]), reverse=True)
        out = []
        for rel, c in rows[:k]:
            out.append({
                "id": c["id"], "title": c["title"], "purpose": c["purpose"],
                "uses": rel["uses"], "useful": rel["useful"], "votes": rel["votes"],
                "reliability": rel["reliability"], "source": rel["source"], "models": c["models"],
            })
        return out

    # ---- evidence synthesis (from the prompt's own attributes) ----
    def _why(self, c: Dict[str, Any], intent) -> List[str]:
        p = c["prompt"]
        why = []
        if intent and intent["purpose"] and intent["purpose"].lower() in c["purpose"].lower():
            why.append(f"Purpose-matched to {c['purpose']}")
        if _ROLE.search(p):
            why.append("Defines an expert role for the model")
        if _FORMAT.search(p):
            why.append("Specifies the output format / structure")
        if _CONSTRAINT.search(p):
            why.append("Includes concrete constraints")
        if c["variables"]:
            why.append("Reusable template with " + ", ".join("{" + v + "}" for v in c["variables"][:3]))
        why.append(f"Quality {c['quality']}/100 from the evaluation pipeline")
        if c["reliability"]["tested"]:
            why.append("Verified on " + ", ".join(c["reliability"]["tested"]))
        return why[:6]

    def _weakness(self, c: Dict[str, Any]) -> str:
        p = c["prompt"]
        if not _FORMAT.search(p):
            return "Output format is loose — add a structure directive for consistent results."
        if not _CONSTRAINT.search(p):
            return "Few explicit constraints — add limits (length, tone, exclusions) to tighten output."
        if not c["variables"]:
            return "Not parameterized — add variables to reuse it across cases."
        if c["prompt_type"] == "image":
            return "Tuned for its subject — swap the style/lens cues for other looks."
        return "Broad coverage — trim to the sections you need for a focused answer."

    def _result(self, c, overall, match, intent, llm=None, votes=None):
        r = self._eff_rel(c, votes)
        why = llm["why"] if (llm and llm.get("why")) else self._why(c, intent)
        weakness = llm["weakness"] if (llm and llm.get("weakness")) else self._weakness(c)
        out = {
            "id": c["id"],
            "title": c["title"],
            "prompt": c["prompt"],
            "template": c["template"],
            "variables": c["variables"],
            "is_template": c["is_template"],
            "prompt_type": c["prompt_type"],
            "purpose": c["purpose"],
            "platform": c["platform"],
            "models": c["models"],
            "scores": {
                "quality": c["quality"],
                "match": match if match is not None else 100,
                "reliability": r["reliability"],
                "freshness": 100,
                "overall": overall if overall is not None else round(
                    c["quality"] * 0.35 + 100 * 0.40 + r["reliability"] * 0.20 + 100 * 0.05),
            },
            "reliability": {
                "uses": r["uses"], "useful": r["useful"], "tested": r["tested"],
                "last_verified": r["last_verified"], "score": r["reliability"],
                "worked": r["worked"], "didnt": r["didnt"], "votes": r["votes"], "source": r["source"],
            },
            "why": why,
            "weakness": weakness,
            "match_source": "llm" if llm else "heuristic",
            "provenance": c["provenance"],
        }
        return out

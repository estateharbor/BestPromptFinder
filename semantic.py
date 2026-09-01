"""
Embeddings-based semantic deduplication (Stage 4b).

Catches near-duplicate prompts that are worded differently, e.g.
  "Write five LinkedIn posts promoting my SaaS product."
  "Create 5 LinkedIn promotional posts for a SaaS business."
which exact/shingle matching misses.

Backend chain (best available wins, degrades gracefully):
  1. sentence-transformers  — true semantic embeddings (all-MiniLM-L6-v2). Best quality.
  2. pure-Python TF-IDF     — no dependencies; term-weighted cosine. Catches reworded
                              dupes far better than raw shingle overlap. Default here.

Dedup is greedy within each purpose bucket: items are visited high-score first, so the
best-scoring copy becomes canonical and lower-scoring near-duplicates are dropped.
"""
import re
import math
import logging
from typing import List, Callable, Any, Tuple

log = logging.getLogger("scraper_agent")

_WORD_RX = re.compile(r"[A-Za-z0-9]+")


# ------------------------------------------------------------------
# Backend selection
# ------------------------------------------------------------------
def _load_sentence_transformer():
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np  # noqa: F401
        model = SentenceTransformer("all-MiniLM-L6-v2")
        return model
    except Exception:
        return None


_ST_MODEL = None
_ST_TRIED = False


def _st_model():
    global _ST_MODEL, _ST_TRIED
    if not _ST_TRIED:
        _ST_TRIED = True
        _ST_MODEL = _load_sentence_transformer()
    return _ST_MODEL


def backend_name() -> str:
    return "sentence-transformers" if _st_model() is not None else "tfidf-python"


# ------------------------------------------------------------------
# Embedding + cosine
# ------------------------------------------------------------------
def _embed_st(texts: List[str]):
    """Dense, L2-normalized numpy vectors."""
    model = _st_model()
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def _embed_tfidf(texts: List[str]) -> List[dict]:
    """Pure-Python TF-IDF, L2-normalized sparse dict vectors (bucket-local IDF)."""
    docs = [[w.lower() for w in _WORD_RX.findall(t)] for t in texts]
    n = len(docs)
    df = {}
    for toks in docs:
        for w in set(toks):
            df[w] = df.get(w, 0) + 1
    vecs = []
    for toks in docs:
        tf = {}
        for w in toks:
            tf[w] = tf.get(w, 0) + 1
        vec = {}
        for w, c in tf.items():
            idf = math.log((1 + n) / (1 + df[w])) + 1.0
            vec[w] = c * idf
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vecs.append({w: v / norm for w, v in vec.items()})
    return vecs


def _cosine(a, b) -> float:
    if isinstance(a, dict):  # tfidf sparse (already normalized)
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(k, 0.0) for k, v in a.items())
    # dense normalized vectors
    return float(sum(x * y for x, y in zip(a, b)))


# ------------------------------------------------------------------
# Public: semantic dedup over row dicts
# ------------------------------------------------------------------
def semantic_dedup(items: List[Any],
                   text_of: Callable[[Any], str],
                   score_of: Callable[[Any], float],
                   purpose_of: Callable[[Any], str],
                   threshold: float = 0.92) -> Tuple[List[Any], int]:
    """Return (kept_items, removed_count). Canonical = highest score in each cluster."""
    use_st = _st_model() is not None

    # Bucket by purpose so comparisons stay local (and semantically coherent).
    buckets = {}
    for it in items:
        buckets.setdefault(purpose_of(it), []).append(it)

    kept, removed = [], 0
    for purpose, group in buckets.items():
        # Best score first -> the survivor of any cluster is its best member.
        group = sorted(group, key=score_of, reverse=True)
        texts = [text_of(it) for it in group]
        vecs = _embed_st(texts) if use_st else _embed_tfidf(texts)

        canon_idx = []
        for i in range(len(group)):
            dup = False
            for j in canon_idx:
                if _cosine(vecs[i], vecs[j]) >= threshold:
                    dup = True
                    break
            if dup:
                removed += 1
            else:
                canon_idx.append(i)
        kept.extend(group[i] for i in canon_idx)

    return kept, removed

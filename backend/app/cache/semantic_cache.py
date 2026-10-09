"""Semantic cache: reuse an answer when a near-identical question was asked over the same documents."""

import hashlib
import json
from datetime import datetime, timezone

import numpy as np

from ..config import settings
from ..db import tx


def docset_key(doc_ids: list[str]) -> str:
    """Hash of the exact document set searched. A different set never shares cache rows."""
    return hashlib.sha256(",".join(sorted(doc_ids)).encode()).hexdigest()[:16]


def lookup(docset: str, embedding: list[float]) -> dict | None:
    """Return the cached result whose question embedding has cosine ≥ threshold.

    Why 0.95: at that level paraphrases ("revenue in 2023?" vs "2023 revenue?") hit,
    while questions differing in a year or metric usually fall below it. Lower (≈0.85)
    starts returning answers to *different* questions, which is worse than a miss.
    """
    with tx() as c:
        rows = c.execute("SELECT embedding, result FROM cache WHERE docset = ?", (docset,)).fetchall()
    if not rows:
        return None
    q = np.asarray(embedding, dtype=np.float32)
    q /= np.linalg.norm(q) or 1.0
    matrix = np.asarray([json.loads(r["embedding"]) for r in rows], dtype=np.float32)
    sims = matrix @ q  # rows are stored normalized, so dot product = cosine
    best = int(np.argmax(sims))
    if sims[best] >= settings.cache_similarity:
        return {**json.loads(rows[best]["result"]), "similarity": float(sims[best])}
    return None


def store(docset: str, query: str, embedding: list[float], result: dict) -> None:
    v = np.asarray(embedding, dtype=np.float32)
    v /= np.linalg.norm(v) or 1.0
    with tx() as c:
        c.execute(
            "INSERT INTO cache (docset, query, embedding, result, created_at) VALUES (?, ?, ?, ?, ?)",
            (docset, query, json.dumps(v.round(6).tolist()), json.dumps(result), datetime.now(timezone.utc).isoformat()),
        )


def invalidate_cache() -> None:
    """Called whenever documents are added or removed."""
    with tx() as c:
        c.execute("DELETE FROM cache")

"""Lazy singletons for the local fastembed models (dense, BM25 sparse, cross-encoder).

Loaded once (and warmed at API start-up, see main.py) and cached on disk after the first download.
"""

import logging
import threading
import time
from functools import lru_cache

from fastembed import SparseTextEmbedding, TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

from .config import settings

log = logging.getLogger(__name__)
_lock = threading.Lock()


@lru_cache(maxsize=1)
def dense_model() -> TextEmbedding:
    return TextEmbedding(settings.dense_model)


@lru_cache(maxsize=1)
def sparse_model() -> SparseTextEmbedding:
    return SparseTextEmbedding(settings.sparse_model)


@lru_cache(maxsize=1)
def rerank_model() -> TextCrossEncoder:
    return TextCrossEncoder(settings.rerank_model)


@lru_cache(maxsize=512)
def _embed_query_cached(text: str) -> tuple[float, ...]:
    with _lock:
        return tuple(next(iter(dense_model().query_embed(text))).tolist())


def embed_query(text: str) -> list[float]:
    """Dense query vector. Cached: the semantic cache, retrieval and memory lookup all embed the
    same question, so one model call serves all three (and repeated questions cost nothing)."""
    return list(_embed_query_cached(text))


def warm_up() -> None:
    """Load all three models and run each once, so the first real question doesn't pay ~3 s of
    model loading and ONNX graph initialisation."""
    t = time.perf_counter()
    try:
        embed_query("warm up")
        list(sparse_model().query_embed("warm up"))
        list(rerank_model().rerank("warm up", ["warm up"]))
        log.info("Models warmed in %.1fs", time.perf_counter() - t)
    except Exception as exc:  # never block start-up; the first request will load them instead
        log.warning("Model warm-up failed: %s", type(exc).__name__)

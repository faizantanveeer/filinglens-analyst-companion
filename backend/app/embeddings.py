"""Embeddings, BM25 sparse vectors and reranking behind one interface.

- Local mode: fastembed models on CPU (bge-small-en-v1.5, Qdrant/bm25, ms-marco-MiniLM-L-6-v2).
  No API cost, nothing leaves the machine; models are warmed at API start-up (see main.py).
- Cloud mode: Jina AI's hosted APIs (jina-embeddings-v3 + jina-reranker-v2) and a pure-Python BM25.
  Serverless functions can't ship ~800 MB of models and onnxruntime, so inference moves to an API.

fastembed is only imported in local mode, so the serverless bundle never needs it.
"""

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from functools import lru_cache

from .config import settings

log = logging.getLogger(__name__)
_lock = threading.Lock()


# ---------- local (fastembed) ----------


@lru_cache(maxsize=1)
def dense_model():
    from fastembed import TextEmbedding

    return TextEmbedding(settings.dense_model)


@lru_cache(maxsize=1)
def sparse_model():
    from fastembed import SparseTextEmbedding

    return SparseTextEmbedding(settings.sparse_model)


@lru_cache(maxsize=1)
def rerank_model():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(settings.rerank_model)


# ---------- cloud (Jina AI) ----------


def _jina(path: str, body: dict, attempts: int = 3) -> dict:
    """POST to Jina with short retries on rate limits / transient errors."""
    req_body = json.dumps(body).encode()
    for attempt in range(attempts):
        req = urllib.request.Request(
            f"https://api.jina.ai/v1/{path}",
            data=req_body,
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.jina_api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"Jina {path} failed: HTTP {exc.code}") from None
        except urllib.error.URLError:
            if attempt < attempts - 1:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"Jina {path} unreachable") from None
    raise RuntimeError(f"Jina {path} failed")


def _jina_embed(texts: list[str], task: str) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), 64):
        r = _jina(
            "embeddings",
            {"model": settings.jina_embedding_model, "task": task, "dimensions": settings.jina_embedding_dim,
             "input": texts[i : i + 64], "truncate": True},
        )
        out += [d["embedding"] for d in sorted(r["data"], key=lambda d: d["index"])]
    return out


# ---------- public interface ----------


def dense_dim() -> int:
    return settings.jina_embedding_dim if settings.cloud else 384


def embed_documents(texts: list[str]) -> list[list[float]]:
    if settings.cloud:
        return _jina_embed(texts, "retrieval.passage")
    return [v.tolist() for v in dense_model().embed(texts)]


@lru_cache(maxsize=512)
def _embed_query_cached(text: str) -> tuple[float, ...]:
    if settings.cloud:
        return tuple(_jina_embed([text], "retrieval.query")[0])
    with _lock:
        return tuple(next(iter(dense_model().query_embed(text))).tolist())


def embed_query(text: str) -> list[float]:
    """Dense query vector. Cached: the semantic cache, retrieval and memory lookup all embed the
    same question, so one model call serves all three (and repeated questions cost nothing)."""
    return list(_embed_query_cached(text))


def sparse_documents(texts: list[str]) -> list[tuple[list[int], list[float]]]:
    if settings.cloud:
        from .retrieval.bm25 import document_vector

        return [document_vector(t) for t in texts]
    return [(s.indices.tolist(), s.values.tolist()) for s in sparse_model().embed(texts)]


def sparse_query(text: str) -> tuple[list[int], list[float]]:
    if settings.cloud:
        from .retrieval.bm25 import query_vector

        return query_vector(text)
    s = next(iter(sparse_model().query_embed(text)))
    return s.indices.tolist(), s.values.tolist()


def rerank_scores(query: str, texts: list[str]) -> list[float]:
    """Relevance score per text. Note the scales differ: ms-marco logits locally (about -11 to +10),
    Jina probabilities in cloud mode (0 to 1), so MIN_RERANK_SCORE is tuned per mode."""
    if not texts:
        return []
    if settings.cloud:
        r = _jina("rerank", {"model": settings.jina_rerank_model, "query": query, "documents": texts, "top_n": len(texts), "return_documents": False})
        scores = [0.0] * len(texts)
        for item in r["results"]:
            scores[item["index"]] = float(item["relevance_score"])
        return scores
    return [float(s) for s in rerank_model().rerank(query, texts)]


def warm_up() -> None:
    """Load the local models once at start-up, so the first question doesn't pay ~3 s of
    model loading and ONNX initialisation. Nothing to warm in cloud mode."""
    if settings.cloud:
        return
    t = time.perf_counter()
    try:
        embed_query("warm up")
        sparse_query("warm up")
        rerank_scores("warm up", ["warm up"])
        log.info("Models warmed in %.1fs", time.perf_counter() - t)
    except Exception as exc:  # never block start-up; the first request will load them instead
        log.warning("Model warm-up failed: %s", type(exc).__name__)

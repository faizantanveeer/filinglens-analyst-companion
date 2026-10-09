"""Hybrid retrieval: dense + BM25, fused with Reciprocal Rank Fusion."""

from dataclasses import dataclass, field

from qdrant_client import models

from ..config import settings
from ..embeddings import embed_query, sparse_model
from ..ingest.indexer import COLLECTION, client, qdrant_lock


@dataclass
class Candidate:
    chunk_id: str
    doc_id: str
    page: int
    section_heading: str
    text: str
    suspicious: bool
    ranks: dict = field(default_factory=dict)  # {"dense": 1, "sparse": 4}
    rrf_score: float = 0.0
    rerank_score: float | None = None


def _doc_filter(doc_ids: list[str] | None) -> models.Filter | None:
    if not doc_ids:
        return None
    return models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchAny(any=doc_ids))])


def rrf_fuse(rankings: dict[str, list[str]], k: int) -> dict[str, float]:
    """score(d) = Σ 1 / (k + rank(d)) across rankings.

    Why RRF: dense cosine and BM25 scores live on different scales; RRF only uses
    ranks, so no score calibration is needed. k=60 damps the influence of the very top
    ranks so one retriever can't dominate.
    """
    scores: dict[str, float] = {}
    for ranked in rankings.values():
        for rank, cid in enumerate(ranked, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return scores


def hybrid_search(query: str, doc_ids: list[str] | None = None) -> list[Candidate]:
    """Query both named vectors (top N each), then fuse.

    Why both: dense finds paraphrases ("how much money did they make"), BM25 finds
    exact tokens ("EBITDA", "FY2023", "Note 14") that embeddings blur.
    """
    n = settings.candidates_per_retriever
    flt = _doc_filter(doc_ids)
    sparse_q = next(iter(sparse_model().query_embed(query)))
    dense_q = embed_query(query)
    qc = client()
    with qdrant_lock:
        dense_hits = qc.query_points(COLLECTION, query=dense_q, using="dense", limit=n, query_filter=flt).points
        sparse_hits = qc.query_points(
            COLLECTION,
            query=models.SparseVector(indices=sparse_q.indices.tolist(), values=sparse_q.values.tolist()),
            using="sparse",
            limit=n,
            query_filter=flt,
        ).points

    by_id: dict[str, Candidate] = {}
    rankings: dict[str, list[str]] = {"dense": [], "sparse": []}
    for name, hits in (("dense", dense_hits), ("sparse", sparse_hits)):
        for rank, h in enumerate(hits, start=1):
            p = h.payload or {}
            cid = p["chunk_id"]
            rankings[name].append(cid)
            cand = by_id.setdefault(
                cid,
                Candidate(
                    chunk_id=cid,
                    doc_id=p["doc_id"],
                    page=p["page"],
                    section_heading=p.get("section_heading", ""),
                    text=p["text"],
                    suspicious=p.get("suspicious", False),
                ),
            )
            cand.ranks[name] = rank

    for cid, score in rrf_fuse(rankings, settings.rrf_k).items():
        by_id[cid].rrf_score = score
    return sorted(by_id.values(), key=lambda c: c.rrf_score, reverse=True)

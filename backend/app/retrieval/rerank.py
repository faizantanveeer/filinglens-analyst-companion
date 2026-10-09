"""Cross-encoder rerank + abstain threshold."""

from ..config import settings
from ..embeddings import rerank_model
from .hybrid import Candidate


def rerank(query: str, candidates: list[Candidate], top_k: int | None = None) -> list[Candidate]:
    """Re-score the fused top candidates with a cross-encoder and keep the best top_k.

    Why: a bi-encoder embeds query and chunk separately; a cross-encoder reads them
    together, so it judges relevance far better. It's slower, so it only sees the
    fused pool (20), never the whole corpus.
    """
    pool = candidates[: settings.rerank_pool]
    if not pool:
        return []
    scores = list(rerank_model().rerank(query, [c.text for c in pool]))
    for c, s in zip(pool, scores):
        c.rerank_score = float(s)
    pool.sort(key=lambda c: c.rerank_score, reverse=True)
    return pool[: top_k or settings.top_k]


def passes_threshold(ranked: list[Candidate], min_score: float | None = None) -> bool:
    """Abstain when even the best chunk is weak: "not found" beats a confident guess."""
    threshold = settings.min_rerank_score if min_score is None else min_score
    return bool(ranked) and ranked[0].rerank_score is not None and ranked[0].rerank_score >= threshold

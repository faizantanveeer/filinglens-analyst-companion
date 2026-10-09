"""Deep research: split the question into sub-questions and retrieve for each."""

from ..config import settings
from ..llm.gateway import LLMConfig, LLMResult, complete, parse_json
from ..retrieval.hybrid import Candidate, hybrid_search
from ..retrieval.rerank import rerank

PROMPT = """Break the user's question about company annual reports into at most {n} focused sub-questions
that together cover it (definitions, the figures involved, drivers, comparisons, risks).
Each sub-question must be answerable from an annual report and searchable on its own.
Return only JSON: {{"sub_questions": ["...", "..."]}}"""


def plan(query: str, cfg: LLMConfig) -> tuple[list[str], LLMResult | None]:
    """Small-model decomposition. Falls back to the original question if planning fails."""
    n = settings.deep_sub_questions
    messages = [{"role": "system", "content": PROMPT.format(n=n)}, {"role": "user", "content": query}]
    try:
        result = complete("small", messages, cfg, json_mode=True, max_tokens=300)
        subs = [str(s).strip()[:300] for s in parse_json(result.text).get("sub_questions", []) if str(s).strip()]
        return subs[:n] or [query], result
    except Exception:
        return [query], None


def research(query: str, sub_questions: list[str], doc_ids: list[str]) -> list[Candidate]:
    """Retrieve + rerank for the original question and each sub-question, then merge.

    Why: one query embedding can only point one way. A broad question ("how resilient is the
    insurance business?") needs evidence from several places in the report at once.
    """
    best: dict[str, Candidate] = {}
    for q in [query, *sub_questions]:
        for c in rerank(q, hybrid_search(q, doc_ids), settings.deep_chunks_per_sub_question):
            if c.chunk_id not in best or (c.rerank_score or 0) > (best[c.chunk_id].rerank_score or 0):
                best[c.chunk_id] = c
    merged = sorted(best.values(), key=lambda c: c.rerank_score or 0, reverse=True)
    return merged[: settings.deep_max_chunks]

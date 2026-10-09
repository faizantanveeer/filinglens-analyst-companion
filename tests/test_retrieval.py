from backend.app.ingest.chunker import Chunk
from backend.app.ingest.indexer import index_chunks
from backend.app.retrieval.hybrid import hybrid_search, rrf_fuse
from backend.app.retrieval.rerank import passes_threshold, rerank


def test_rrf_rewards_agreement():
    scores = rrf_fuse({"dense": ["a", "b", "c"], "sparse": ["c", "b", "x"]}, k=60)
    assert scores["b"] > scores["a"]  # ranked 2nd by both beats 1st by one
    assert abs(scores["a"] - 1 / 61) < 1e-12


def test_exact_term_is_retrieved_in_top3():
    docs = [
        "Adjusted EBITDA for FY2024 was $4.2 billion, up from $3.9 billion in FY2023.",
        "Our employees volunteered thousands of hours in local communities.",
        "The board of directors met eleven times during the year.",
        "Revenue from the railroad segment declined due to lower volumes.",
        "Insurance float rose to $168 billion at year end.",
    ]
    index_chunks([Chunk(f"r:{i}", "r", page=i + 1, section_heading="", text=t) for i, t in enumerate(docs)])
    q = "What was EBITDA in FY2024?"
    top = rerank(q, hybrid_search(q, ["r"]), 3)
    assert top[0].page == 1
    assert passes_threshold(top)
    q2 = "Who won the 1998 football world cup?"
    assert not passes_threshold(rerank(q2, hybrid_search(q2, ["r"]), 3))

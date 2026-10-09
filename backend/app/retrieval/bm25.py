"""Dependency-free BM25 sparse vectors (cloud mode).

Qdrant applies the IDF part server-side (Modifier.IDF over the whole collection), so each document
vector only needs the BM25 term-frequency weight, and the query vector just marks which terms occur.
Local mode uses fastembed's Qdrant/bm25 instead (same idea, with a stemmer); this keeps the serverless
bundle free of onnxruntime.
"""

import re
import zlib
from collections import Counter

K1, B, AVG_DOC_LEN = 1.2, 0.75, 256.0

# Short stopword list: enough to stop "the/of/and" dominating, small enough to keep finance terms.
STOPWORDS = frozenset(
    "a an and are as at be but by for from has have he her his i if in into is it its of on or our "
    "she so than that the their them there these they this to was we were what when where which who "
    "will with would you your".split()
)
TOKEN = re.compile(r"[a-z0-9]+(?:[.'][a-z0-9]+)*")


def tokens(text: str) -> list[str]:
    """Lowercase alphanumerics; keeps '10-k' as '10','k', 'fy2024', '37.4' and "berkshire's"."""
    out = []
    for t in TOKEN.findall(text.lower()):
        t = t.removesuffix("'s")
        if t and t not in STOPWORDS:
            out.append(t)
    return out


def term_id(term: str) -> int:
    """Stable 31-bit id (Python's hash() is salted per process, so it can't be used)."""
    return zlib.crc32(term.encode()) & 0x7FFFFFFF


def _merge(weights: dict[int, float]) -> tuple[list[int], list[float]]:
    items = sorted(weights.items())
    return [i for i, _ in items], [round(w, 4) for _, w in items]


def document_vector(text: str) -> tuple[list[int], list[float]]:
    toks = tokens(text)
    if not toks:
        return [], []
    tf, n = Counter(toks), len(toks)
    norm = K1 * (1 - B + B * n / AVG_DOC_LEN)
    weights: dict[int, float] = {}
    for term, f in tf.items():
        tid = term_id(term)
        weights[tid] = weights.get(tid, 0.0) + f * (K1 + 1) / (f + norm)
    return _merge(weights)


def query_vector(text: str) -> tuple[list[int], list[float]]:
    return _merge({term_id(t): 1.0 for t in set(tokens(text))})

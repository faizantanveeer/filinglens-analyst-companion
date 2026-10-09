"""Cross-chat memory (opt-in): durable facts about the user, never facts about documents."""

import json
import logging
from datetime import datetime, timezone

import numpy as np

from .config import settings
from .db import tx
from .embeddings import embed_query
from .llm.gateway import LLMConfig, complete, parse_json
from .pipeline.guard_input import looks_like_injection, redact_pii

log = logging.getLogger(__name__)

EXTRACT_PROMPT = """You decide whether a chat turn reveals a DURABLE fact about the USER worth remembering across chats:
their role, the companies or sectors they follow, recurring interests, or preferences for how answers are given
(units, depth, format). Do NOT record facts about companies or documents, one-off questions, or anything sensitive
(health, finances of a person, contact details). Most turns reveal nothing: then return an empty list.
Write each memory as one short sentence starting with "User".
Return only JSON: {"memories": ["User ...", ...]} with at most 2 items."""


def _vec(text: str) -> np.ndarray:
    v = np.asarray(embed_query(text), dtype=np.float32)
    return v / (np.linalg.norm(v) or 1.0)


def list_memories(owner: str) -> list[dict]:
    with tx() as c:
        rows = c.execute("SELECT id, content, source_session, created_at FROM memories WHERE owner = ? ORDER BY id DESC", (owner,)).fetchall()
    return [dict(r) for r in rows]


def delete(owner: str, mid: int) -> bool:
    with tx() as c:
        return c.execute("DELETE FROM memories WHERE id = ? AND owner = ?", (mid, owner)).rowcount > 0


def clear(owner: str) -> int:
    with tx() as c:
        return c.execute("DELETE FROM memories WHERE owner = ?", (owner,)).rowcount


def add(owner: str, content: str, source_session: str | None = None) -> bool:
    """Store a memory unless it's a near-duplicate of one we have. Oldest are evicted past the cap."""
    content = " ".join(content.split())[:200]
    if not content or looks_like_injection(content):
        return False
    content, _ = redact_pii(content)
    v = _vec(content)
    with tx() as c:
        rows = c.execute("SELECT id, embedding FROM memories WHERE owner = ?", (owner,)).fetchall()
        for r in rows:
            if float(np.dot(np.asarray(json.loads(r["embedding"]), dtype=np.float32), v)) >= settings.memory_dedupe_similarity:
                return False
        c.execute(
            "INSERT INTO memories (owner, content, embedding, source_session, created_at) VALUES (?, ?, ?, ?, ?)",
            (owner, content, json.dumps(v.round(6).tolist()), source_session, datetime.now(timezone.utc).isoformat()),
        )
        c.execute(
            "DELETE FROM memories WHERE owner = ? AND id NOT IN (SELECT id FROM memories WHERE owner = ? ORDER BY id DESC LIMIT ?)",
            (owner, owner, settings.memory_max_per_owner),
        )
    return True


def relevant(owner: str, query: str) -> list[str]:
    """Top memories for this question (cosine on local embeddings, so no tokens spent)."""
    with tx() as c:
        rows = c.execute("SELECT content, embedding FROM memories WHERE owner = ?", (owner,)).fetchall()
    if not rows:
        return []
    q = _vec(query)
    scored = sorted(((float(np.dot(np.asarray(json.loads(r["embedding"]), dtype=np.float32), q)), r["content"]) for r in rows), reverse=True)
    return [text for score, text in scored[: settings.memory_top_k] if score >= settings.memory_min_similarity]


def extract_and_store(owner: str, sid: str | None, question: str, cfg: LLMConfig) -> int:
    """Small-model pass over the user's question only (answers are document facts, not user facts)."""
    messages = [{"role": "system", "content": EXTRACT_PROMPT}, {"role": "user", "content": f"User message: {question[:1000]}"}]
    try:
        result = complete("small", messages, cfg, json_mode=True, max_tokens=120)
        items = parse_json(result.text).get("memories") or []
    except Exception as exc:
        log.warning("Memory extraction failed: %s", type(exc).__name__)
        return 0
    return sum(add(owner, str(m), sid) for m in items[:2] if str(m).strip())

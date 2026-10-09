"""Chat sessions: storage, search, and context management for long conversations."""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import settings
from .db import tx
from .llm.gateway import LLMConfig, complete, parse_json

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def title_from(question: str) -> str:
    """Free title from the first question (no LLM call); the user can rename it."""
    t = " ".join(question.split())
    return t if len(t) <= 60 else t[:57].rsplit(" ", 1)[0] + "…"


# ---------- CRUD (every query is scoped to the owner) ----------


def create(owner: str, title: str = "New chat") -> dict:
    sid, now = uuid.uuid4().hex[:16], _now()
    with tx() as c:
        c.execute("INSERT INTO sessions (id, owner, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (sid, owner, title, now, now))
    return {"id": sid, "title": title, "created_at": now, "updated_at": now, "pinned": False}


def get(owner: str, sid: str) -> dict | None:
    with tx() as c:
        row = c.execute("SELECT id, title, created_at, updated_at, pinned FROM sessions WHERE id = ? AND owner = ?", (sid, owner)).fetchone()
    return _row(row) if row else None


def _row(r) -> dict:
    d = dict(r)
    d["pinned"] = bool(d.get("pinned"))
    return d


def list_sessions(owner: str, query: str = "", limit: int = 100) -> list[dict]:
    """Pinned first, then newest. With a query, match titles or any message text; return a snippet of the match."""
    with tx() as c:
        if not query.strip():
            rows = c.execute(
                "SELECT id, title, created_at, updated_at, pinned, NULL AS snippet FROM sessions WHERE owner = ? ORDER BY pinned DESC, updated_at DESC LIMIT ?",
                (owner, limit),
            ).fetchall()
        else:
            escaped = query.strip().replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")  # LIKE wildcards are literal
            like = f"%{escaped}%"
            rows = c.execute(
                r"""SELECT s.id, s.title, s.created_at, s.updated_at, s.pinned,
                          (SELECT m.content FROM messages m WHERE m.session_id = s.id AND m.content LIKE ? ESCAPE '\' ORDER BY m.id LIMIT 1) AS snippet
                   FROM sessions s
                   WHERE s.owner = ? AND (s.title LIKE ? ESCAPE '\'
                         OR EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id AND m.content LIKE ? ESCAPE '\'))
                   ORDER BY s.pinned DESC, s.updated_at DESC LIMIT ?""",
                (like, owner, like, like, limit),
            ).fetchall()
    out = []
    for r in rows:
        d = _row(r)
        if d["snippet"]:
            d["snippet"] = _snippet(d["snippet"], query)
        out.append(d)
    return out


def _snippet(text: str, query: str, width: int = 90) -> str:
    text = " ".join(text.replace("[", " [").split())
    i = text.lower().find(query.strip().lower())
    start = max(0, i - width // 3)
    s = text[start : start + width]
    return ("…" if start else "") + s + ("…" if start + width < len(text) else "")


def rename(owner: str, sid: str, title: str) -> bool:
    return update(owner, sid, title=title)


def update(owner: str, sid: str, title: str | None = None, pinned: bool | None = None) -> bool:
    """Rename and/or pin. Neither changes updated_at, so the chat keeps its place in history."""
    sets, args = [], []
    if title is not None:
        sets.append("title = ?")
        args.append(" ".join(title.split())[:120] or "Untitled chat")
    if pinned is not None:
        sets.append("pinned = ?")
        args.append(1 if pinned else 0)
    if not sets:
        return get(owner, sid) is not None
    with tx() as c:
        cur = c.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id = ? AND owner = ?", (*args, sid, owner))
    return cur.rowcount > 0


def delete(owner: str, sid: str) -> bool:
    """Deletes the session, its messages and its summary (ON DELETE CASCADE).
    Cross-chat memories are kept; they're managed separately in Settings."""
    with tx() as c:
        cur = c.execute("DELETE FROM sessions WHERE id = ? AND owner = ?", (sid, owner))
    return cur.rowcount > 0


def delete_all(owner: str) -> int:
    with tx() as c:
        return c.execute("DELETE FROM sessions WHERE owner = ?", (owner,)).rowcount


def messages(owner: str, sid: str) -> list[dict] | None:
    if not get(owner, sid):
        return None
    with tx() as c:
        rows = c.execute("SELECT id, role, content, payload, created_at FROM messages WHERE session_id = ? ORDER BY id", (sid,)).fetchall()
    return [{**dict(r), "payload": json.loads(r["payload"]) if r["payload"] else None} for r in rows]


def record_turn(owner: str, sid: str, question: str, answer: str, payload: dict) -> None:
    """Persist one completed question/answer pair and bump the session. The first turn names the session."""
    now = _now()
    with tx() as c:
        row = c.execute("SELECT title, (SELECT COUNT(*) FROM messages WHERE session_id = ?) AS n FROM sessions WHERE id = ? AND owner = ?", (sid, sid, owner)).fetchone()
        if not row:
            return
        c.execute("INSERT INTO messages (session_id, role, content, payload, created_at) VALUES (?, 'user', ?, NULL, ?)", (sid, question, now))
        c.execute("INSERT INTO messages (session_id, role, content, payload, created_at) VALUES (?, 'assistant', ?, ?, ?)", (sid, answer, json.dumps(payload), now))
        title = title_from(question) if row["n"] == 0 and row["title"] == "New chat" else row["title"]
        c.execute("UPDATE sessions SET updated_at = ?, title = ? WHERE id = ?", (now, title, sid))


# ---------- context management ----------


@dataclass
class Conversation:
    """What the pipeline sees of a session: a rolling summary of older turns plus the recent turns verbatim."""

    owner: str
    session_id: str | None = None
    summary: str = ""
    recent: list[dict] = field(default_factory=list)  # [{role, content}], trimmed


def _trim(text: str) -> str:
    """Drop citation markers (they point at an old context) and cap the length."""
    import re

    text = " ".join(re.sub(r"\[[CW]\d+\]", "", text).split())
    n = settings.context_turn_chars
    return text if len(text) <= n else text[: n - 1] + "…"


def conversation(owner: str, sid: str | None) -> Conversation:
    """Bounded context for the next turn, however long the session is.

    Why: only the query-rewrite step (small model) reads conversation history; the grounded
    answer sees the standalone question plus document chunks. Keeping the last few turns
    verbatim and folding everything older into a short summary keeps that prompt small and
    roughly constant in size, instead of growing with every turn.
    """
    convo = Conversation(owner=owner, session_id=sid)
    if not sid or not get(owner, sid):
        return convo
    with tx() as c:
        ctx = c.execute("SELECT summary, covered FROM session_context WHERE session_id = ?", (sid,)).fetchone()
        rows = c.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY id", (sid,)).fetchall()
    covered = ctx["covered"] if ctx else 0
    convo.summary = ctx["summary"] if ctx else ""
    # Everything not yet summarised is passed verbatim, so no turn falls through the gap between
    # the window and the summary. The cap only bites if folding keeps failing.
    cap = (settings.context_recent_turns + settings.context_fold_batch_turns) * 2
    convo.recent = [{"role": r["role"], "content": _trim(r["content"])} for r in rows[covered:][-cap:]]
    return convo


SUMMARY_PROMPT = """You maintain a running summary of a conversation about company annual reports.
Merge the EARLIER SUMMARY with the NEW TURNS into one updated summary of at most {words} words.
Keep: companies, years, segments, metrics and figures discussed, conclusions reached, and open questions.
Drop pleasantries and repetition. Write plain prose, third person ("The user asked…").
Return only JSON: {{"summary": "..."}}"""


def maybe_fold(owner: str, sid: str, cfg: LLMConfig) -> bool:
    """Fold turns that fell out of the verbatim window into the rolling summary (small model).

    Runs after a turn is recorded, in the background. It only acts once enough turns
    have piled up outside the window, so most turns cost nothing extra.
    """
    with tx() as c:
        ctx = c.execute("SELECT summary, covered FROM session_context WHERE session_id = ?", (sid,)).fetchone()
        rows = c.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY id", (sid,)).fetchall()
    covered = ctx["covered"] if ctx else 0
    keep = settings.context_recent_turns * 2
    outside = len(rows) - covered - keep  # messages older than the verbatim window, not yet summarised
    if outside < settings.context_fold_batch_turns * 2:
        return False
    fold = rows[covered : len(rows) - keep]
    turns = "\n".join(f"{r['role']}: {_trim(r['content'])}" for r in fold)
    earlier = ctx["summary"] if ctx else "(none)"
    messages_ = [
        {"role": "system", "content": SUMMARY_PROMPT.format(words=settings.summary_max_words)},
        {"role": "user", "content": f"EARLIER SUMMARY:\n{earlier}\n\nNEW TURNS:\n{turns}"},
    ]
    try:
        result = complete("small", messages_, cfg, json_mode=True, max_tokens=400)
        summary = str(parse_json(result.text).get("summary", "")).strip()
    except Exception as exc:  # the next turn simply tries again
        log.warning("Summary fold failed for %s: %s", sid, type(exc).__name__)
        return False
    if not summary:
        return False
    with tx() as c:
        c.execute(
            "INSERT INTO session_context (session_id, summary, covered) VALUES (?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET summary = excluded.summary, covered = excluded.covered",
            (sid, summary[:2000], covered + len(fold)),
        )
    return True

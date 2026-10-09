"""SQLite: document metadata, semantic cache rows and request traces. Zero setup, one file."""

import sqlite3
import threading
from contextlib import contextmanager

from .config import settings

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL,          -- processing | ready | error
    pages INTEGER DEFAULT 0,
    chunks INTEGER DEFAULT 0,
    suspicious_chunks INTEGER DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    docset TEXT NOT NULL,
    query TEXT NOT NULL,
    embedding TEXT NOT NULL,       -- JSON list of floats (normalized)
    result TEXT NOT NULL,          -- JSON: answer, answer_type, citations
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cache_docset ON cache(docset);
CREATE TABLE IF NOT EXISTS traces (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    question TEXT,                 -- after PII redaction
    route TEXT,                    -- answer | not_found | refusal | out_of_scope | cached | error
    intent TEXT,
    complexity TEXT,
    model TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost REAL DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    steps TEXT,                    -- JSON {step: ms}
    chunk_ids TEXT,                -- JSON list
    cache_hit INTEGER DEFAULT 0,
    verification TEXT,             -- pass | retry_pass | fail | skipped
    judge TEXT
);
-- Chat sessions, scoped to an anonymous per-browser owner id (X-Client-Id).
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_owner ON sessions(owner, updated_at);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,            -- user | assistant
    content TEXT NOT NULL,
    payload TEXT,                  -- JSON: citations, chart, suggestions, answer_type, meta, steps, deep
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, id);
-- Rolling summary of the older part of a long session (context management).
CREATE TABLE IF NOT EXISTS session_context (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    covered INTEGER NOT NULL       -- number of messages folded into the summary
);
-- Cross-chat memory: durable facts about the user, never about documents. Opt-in.
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding TEXT NOT NULL,       -- JSON list of floats (normalized)
    source_session TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS memories_owner ON memories(owner);
"""


def _connect() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # deleting a session deletes its messages and summary
    return conn


_conn = _connect()
_conn.executescript(SCHEMA)

# Lightweight migrations for databases created by earlier versions.
_MIGRATIONS = {
    "documents": {
        "filetype": "TEXT DEFAULT 'pdf'",
        "progress": "REAL DEFAULT 0",  # 0..1 while processing
        "stage": "TEXT",  # e.g. "Parsing 48/152 pages"
        "source_url": "TEXT",  # where an imported filing came from (EDGAR)
        "protected": "INTEGER DEFAULT 0",  # the bundled sample in the public demo; can't be deleted
    },
    "traces": {
        "owner": "TEXT",  # X-Client-Id, so Insights only shows a visitor their own requests
    },
}
for _table, _cols in _MIGRATIONS.items():
    _have = {r["name"] for r in _conn.execute(f"PRAGMA table_info({_table})")}
    for _col, _ddl in _cols.items():
        if _col not in _have:
            _conn.execute(f"ALTER TABLE {_table} ADD COLUMN {_col} {_ddl}")
_conn.commit()


@contextmanager
def tx():
    """One shared connection guarded by a lock: simple and safe for a single-process app."""
    with _lock:
        try:
            yield _conn
            _conn.commit()
        except Exception:
            _conn.rollback()
            raise

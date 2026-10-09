"""Relational storage: documents, files, sessions, memories, cache and traces.

Two backends behind one tiny interface, `tx()` yielding an object with `.execute(sql, params)`:
- SQLite (local mode): zero setup, one file under DATA_DIR.
- Postgres (cloud mode, when DATABASE_URL is set): e.g. Neon. Serverless functions have no
  persistent disk, so state must live in a hosted database.
SQL is written once in SQLite style ("?" placeholders); the Postgres adapter translates it.
"""

import re
import sqlite3
import threading
import time
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
-- Accounts. Guests have no email; signing up fills it in (same id, so data stays linked).
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE,
    password_hash TEXT,
    role TEXT NOT NULL,            -- guest | user | admin
    created_at TEXT NOT NULL,
    created_ip TEXT,
    questions_used INTEGER NOT NULL DEFAULT 0,
    period TEXT                    -- YYYY-MM the question count belongs to (monthly reset for users)
);
-- Login sessions: only the SHA-256 of each bearer token is stored.
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions(user_id);
-- Failed-login log for rate limiting (keys: email:<addr>, ip:<addr>).
CREATE TABLE IF NOT EXISTS auth_attempts (
    key TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_attempts_key ON auth_attempts(key, at);
-- In-progress chunked uploads and who started them.
CREATE TABLE IF NOT EXISTS uploads (
    upload_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
-- Raw uploaded files in cloud mode (no persistent disk), stored as ordered pieces.
CREATE TABLE IF NOT EXISTS files (
    doc_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    data BLOB NOT NULL,
    PRIMARY KEY (doc_id, seq)
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

# Columns added after the first release (older databases are upgraded in place).
MIGRATIONS = {
    "documents": {
        "filetype": "TEXT DEFAULT 'pdf'",
        "progress": "REAL DEFAULT 0",  # 0..1 while processing
        "stage": "TEXT",  # e.g. "Parsing 48/152 pages"
        "source_url": "TEXT",  # where an imported filing came from (EDGAR)
        "protected": "INTEGER DEFAULT 0",  # the bundled sample in the public demo; can't be deleted
        "owner_id": "TEXT",  # NULL only for the protected public sample
    },
    "traces": {
        "owner": "TEXT",  # X-Client-Id, so Insights only shows a visitor their own requests
    },
    "sessions": {
        "pinned": "INTEGER DEFAULT 0",  # pinned chats are listed first, in their own section
    },
}


# ---------- Postgres adapter (cloud mode) ----------


class _PgCursor:
    def __init__(self, cur):
        self._cur = cur

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    def fetchone(self):
        return self._cur.fetchone() if self._cur.description else None

    def fetchall(self):
        return self._cur.fetchall() if self._cur.description else []

    def __iter__(self):
        return iter(self.fetchall())


class _PgConnection:
    """Speaks the sqlite3 subset this app uses: '?' placeholders, case-insensitive LIKE, dict rows."""

    def __init__(self, url: str):
        self._url = url
        self._conn = None
        self._last_used = 0.0

    def _ensure(self):
        import psycopg
        from psycopg.rows import dict_row

        stale = self._conn is not None and time.time() - self._last_used > 120
        if self._conn is not None and stale:
            try:  # serverless Postgres (Neon) closes idle connections; ping before reuse
                self._conn.execute("SELECT 1")
            except Exception:
                self._conn = None
        if self._conn is None or self._conn.closed or self._conn.broken:
            self._conn = psycopg.connect(self._url, row_factory=dict_row, connect_timeout=15)
        self._last_used = time.time()
        return self._conn

    @staticmethod
    def translate(sql: str) -> str:
        sql = re.sub(r"\bLIKE\b", "ILIKE", sql)  # SQLite's LIKE is case-insensitive; match that
        return sql.replace("%", "%%").replace("?", "%s")

    def execute(self, sql: str, params=()):
        return _PgCursor(self._ensure().execute(self.translate(sql), tuple(params)))

    def commit(self):
        if self._conn is not None and not self._conn.closed:
            self._conn.commit()

    def rollback(self):
        if self._conn is not None and not self._conn.closed:
            try:
                self._conn.rollback()
            except Exception:
                self._conn = None


def _pg_schema(sql: str) -> list[str]:
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY").replace(" BLOB ", " BYTEA ")
    sql = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in sql.split(";") if s.strip()]


# ---------- connection setup ----------

IS_POSTGRES = settings.cloud and bool(settings.database_url)


def _connect():
    if IS_POSTGRES:
        conn = _PgConnection(settings.database_url)
        for stmt in _pg_schema(SCHEMA):
            conn._ensure().execute(stmt)
        for table, cols in MIGRATIONS.items():
            for col, ddl in cols.items():
                conn._ensure().execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}")
        conn.commit()
        return conn
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # deleting a session deletes its messages and summary
    conn.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, ddl in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    conn.commit()
    return conn


_conn = _connect()

# Documents uploaded before accounts existed have no owner. Never let them become public:
# park them under a placeholder owner that only admins can see.
_conn.execute("UPDATE documents SET owner_id = 'legacy' WHERE owner_id IS NULL AND (protected IS NULL OR protected = 0)")
_conn.commit()


@contextmanager
def tx():
    """One shared connection guarded by a lock: simple and safe for a single-process app
    (and for one serverless instance, which handles its requests in one process)."""
    with _lock:
        try:
            yield _conn
            _conn.commit()
        except Exception:
            _conn.rollback()
            raise

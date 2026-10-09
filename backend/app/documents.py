"""Document lifecycle: register an upload, index it in the background, list, delete."""

import hashlib
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .cache.semantic_cache import invalidate_cache
from .config import settings
from .db import tx
from .ingest.chunker import chunk_pages
from .ingest.indexer import delete_document as delete_vectors
from .ingest.indexer import flag_suspicious, index_chunks
from .ingest.parser import page_count, parse_batches

log = logging.getLogger(__name__)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_by_hash(digest: str, owner_id: str | None = None) -> dict | None:
    """De-duplicate within one owner only: matching another user's file would hand over their document."""
    with tx() as c:
        if owner_id is None:
            row = c.execute("SELECT * FROM documents WHERE sha256 = ? AND status != 'error' AND owner_id IS NULL", (digest,)).fetchone()
        else:
            row = c.execute("SELECT * FROM documents WHERE sha256 = ? AND status != 'error' AND owner_id = ?", (digest, owner_id)).fetchone()
    return dict(row) if row else None


def register(doc_id: str, filename: str, digest: str, filetype: str = "pdf", source_url: str | None = None, owner_id: str | None = None) -> dict:
    """owner_id None = public (only for the protected sample); every upload has an owner."""
    now = datetime.now(timezone.utc).isoformat()
    with tx() as c:
        c.execute(
            "INSERT INTO documents (id, filename, sha256, status, created_at, filetype, stage, source_url, owner_id) "
            "VALUES (?, ?, ?, 'processing', ?, ?, 'Queued', ?, ?)",
            (doc_id, filename, digest, now, filetype, source_url, owner_id),
        )
    return get(doc_id)  # type: ignore[return-value]


def get(doc_id: str) -> dict | None:
    with tx() as c:
        row = c.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def list_all() -> list[dict]:
    with tx() as c:
        rows = c.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


# ---------- access control ----------


def list_for(user: dict) -> list[dict]:
    """Your documents plus the public sample; admins see everything."""
    if user["role"] == "admin":
        return list_all()
    with tx() as c:
        rows = c.execute("SELECT * FROM documents WHERE owner_id = ? OR owner_id IS NULL ORDER BY created_at DESC", (user["id"],)).fetchall()
    return [dict(r) for r in rows]


def ready_ids_for(user: dict) -> list[str]:
    return sorted(d["id"] for d in list_for(user) if d["status"] == "ready" and (user["role"] != "admin" or d["owner_id"] in (None, user["id"])))


def can_read(doc: dict | None, user: dict) -> bool:
    return bool(doc) and (user["role"] == "admin" or doc["owner_id"] is None or doc["owner_id"] == user["id"])


def can_delete(doc: dict | None, user: dict) -> bool:
    if not doc:
        return False
    if user["role"] == "admin":
        return True
    return doc["owner_id"] == user["id"] and not doc.get("protected")


def count_owned(owner_id: str) -> int:
    with tx() as c:
        return c.execute("SELECT COUNT(*) AS n FROM documents WHERE owner_id = ?", (owner_id,)).fetchone()["n"]


def ready_ids() -> list[str]:
    with tx() as c:
        return [r["id"] for r in c.execute("SELECT id FROM documents WHERE status = 'ready' ORDER BY id")]


def filetype_of(doc_id: str) -> str:
    doc = get(doc_id)
    return (doc or {}).get("filetype") or "pdf"


def file_path(doc_id: str, filetype: str | None = None) -> Path:
    ext = {"pdf": "pdf", "html": "html", "txt": "txt", "epub": "epub"}[filetype or filetype_of(doc_id)]
    return settings.uploads_dir / f"{doc_id}.{ext}"


# ---------- file storage ----------
# Local mode: files live under DATA_DIR/uploads. Cloud mode (serverless, no persistent disk):
# files live in the database as ordered pieces and are materialised to /tmp when needed.

PIECE = 4 * 1024 * 1024  # also the upload chunk size: under Vercel's 4.5 MB request-body limit


def add_piece(doc_id: str, seq: int, data: bytes) -> None:
    with tx() as c:
        c.execute("DELETE FROM files WHERE doc_id = ? AND seq = ?", (doc_id, seq))
        c.execute("INSERT INTO files (doc_id, seq, data) VALUES (?, ?, ?)", (doc_id, seq, data))


def read_pieces(doc_id: str) -> bytes:
    with tx() as c:
        rows = c.execute("SELECT data FROM files WHERE doc_id = ? ORDER BY seq", (doc_id,)).fetchall()
    return b"".join(bytes(r["data"]) for r in rows)


def drop_pieces(doc_id: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM files WHERE doc_id = ?", (doc_id,))


def save_file(doc_id: str, filetype: str, data: bytes) -> None:
    """Persist the original file where this deployment keeps files."""
    if settings.cloud:
        drop_pieces(doc_id)
        for seq, start in enumerate(range(0, len(data), PIECE)):
            add_piece(doc_id, seq, data[start : start + PIECE])
    else:
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        file_path(doc_id, filetype).write_bytes(data)


def local_path(doc_id: str, filetype: str | None = None) -> Path:
    """A path on local disk for parsing/rendering; in cloud mode, fetched from the database once
    per warm instance (cold instances start with an empty /tmp)."""
    path = file_path(doc_id, filetype)
    if settings.cloud and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(read_pieces(doc_id))
    return path


def _progress(doc_id: str, fraction: float, stage: str) -> None:
    with tx() as c:
        c.execute("UPDATE documents SET progress=?, stage=? WHERE id=?", (round(fraction, 3), stage, doc_id))


def ingest(doc_id: str) -> None:
    """Parse → chunk → flag → index, batch by batch, with live progress for the UI.

    Why batches: while this thread embeds and indexes batch N, worker processes are already
    parsing batch N+1, so the two slowest stages overlap instead of running back to back.
    """
    try:
        ftype = filetype_of(doc_id)
        path = local_path(doc_id, ftype)
        total = page_count(path, ftype)
        _progress(doc_id, 0.0, f"Parsing 0/{total} pages")
        done_pages, n_chunks, suspicious = 0, 0, 0
        for batch in parse_batches(path, ftype, settings.parse_workers, settings.parse_batch_pages):
            chunks = chunk_pages(doc_id, batch, start=n_chunks)
            suspicious += flag_suspicious(chunks)
            index_chunks(chunks)
            done_pages += len(batch)
            n_chunks += len(chunks)
            _progress(doc_id, done_pages / total, f"Indexed {done_pages}/{total} pages · {n_chunks} chunks")
        with tx() as c:
            c.execute(
                "UPDATE documents SET status='ready', pages=?, chunks=?, suspicious_chunks=?, progress=1, stage=NULL WHERE id=?",
                (total, n_chunks, suspicious, doc_id),
            )
        invalidate_cache()  # the document set changed, so cached answers may be stale
    except Exception as exc:  # surface the failure in the UI instead of a stuck "processing"
        log.exception("Ingest failed for %s", doc_id)
        with tx() as c:
            c.execute("UPDATE documents SET status='error', error=? WHERE id=?", (str(exc)[:300], doc_id))


def page_cache_dir(doc_id: str, create: bool = True) -> Path:
    d = settings.data_dir / "pages" / doc_id
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def delete(doc_id: str) -> bool:
    if not get(doc_id):
        return False
    delete_vectors(doc_id)
    file_path(doc_id).unlink(missing_ok=True)
    drop_pieces(doc_id)
    shutil.rmtree(page_cache_dir(doc_id, create=False), ignore_errors=True)  # rendered page previews
    with tx() as c:
        c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    invalidate_cache()
    return True

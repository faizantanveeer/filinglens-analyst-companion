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


def find_by_hash(digest: str) -> dict | None:
    with tx() as c:
        row = c.execute("SELECT * FROM documents WHERE sha256 = ? AND status != 'error'", (digest,)).fetchone()
    return dict(row) if row else None


def register(doc_id: str, filename: str, digest: str, filetype: str = "pdf", source_url: str | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with tx() as c:
        c.execute(
            "INSERT INTO documents (id, filename, sha256, status, created_at, filetype, stage, source_url) "
            "VALUES (?, ?, ?, 'processing', ?, ?, 'Queued', ?)",
            (doc_id, filename, digest, now, filetype, source_url),
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


def ready_ids() -> list[str]:
    with tx() as c:
        return [r["id"] for r in c.execute("SELECT id FROM documents WHERE status = 'ready' ORDER BY id")]


def filetype_of(doc_id: str) -> str:
    doc = get(doc_id)
    return (doc or {}).get("filetype") or "pdf"


def file_path(doc_id: str, filetype: str | None = None) -> Path:
    ext = {"pdf": "pdf", "html": "html", "txt": "txt", "epub": "epub"}[filetype or filetype_of(doc_id)]
    return settings.uploads_dir / f"{doc_id}.{ext}"


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
        path = file_path(doc_id, ftype)
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
    shutil.rmtree(page_cache_dir(doc_id, create=False), ignore_errors=True)  # rendered page previews
    with tx() as c:
        c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    invalidate_cache()
    return True

"""Documents → per-page markdown, parsed in parallel worker processes."""

import os
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pymupdf
import pymupdf4llm

# MuPDF opens all of these natively, so no extra dependency: SEC EDGAR filings are HTML,
# and plain text / markdown / EPUB come for free. (DOCX would need another library.)
SUPPORTED = {
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".txt": "txt",
    ".md": "txt",
    ".epub": "epub",
}


@dataclass
class Page:
    number: int  # 1-based page in the document as rendered (what a PDF viewer shows)
    markdown: str


def filetype_for(name: str) -> str | None:
    return SUPPORTED.get(Path(name).suffix.lower())


def open_document(path: Path, filetype: str) -> pymupdf.Document:
    """PDFs open directly; HTML/TXT/EPUB are laid out into pages by MuPDF first."""
    if filetype == "pdf":
        return pymupdf.open(path)
    return pymupdf.open(stream=path.read_bytes(), filetype=filetype)


def page_count(path: Path, filetype: str) -> int:
    with open_document(path, filetype) as doc:
        return doc.page_count


def _parse_range(args: tuple[str, str, list[int]]) -> list[tuple[int, str]]:
    """Worker: convert one range of pages. Runs in a separate process (module-level for pickling)."""
    path, filetype, pages = args
    with open_document(Path(path), filetype) as doc:
        parts = pymupdf4llm.to_markdown(doc, pages=pages, page_chunks=True, show_progress=False)
    return [(p + 1, part["text"]) for p, part in zip(pages, parts)]


def parse_batches(path: Path, filetype: str = "pdf", workers: int | None = None, batch_pages: int = 16) -> Iterator[list[Page]]:
    """Yield pages in document order, batch by batch, while later batches are still being parsed.

    Why parallel: layout analysis (tables, headings) is CPU-bound and per-page independent, so
    4 processes roughly halve parse time (117 s → 60 s on the 152-page eval report).
    Why batches: the caller embeds batch N while workers parse batch N+1, overlapping the two
    slowest stages instead of running them back to back.
    """
    n = page_count(path, filetype)
    workers = workers or min(4, os.cpu_count() or 1)
    ranges = [(str(path), filetype, list(range(i, min(i + batch_pages, n)))) for i in range(0, n, batch_pages)]
    if workers <= 1 or len(ranges) == 1:
        for r in ranges:
            yield [Page(p, t) for p, t in _parse_range(r)]
        return
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for part in pool.map(_parse_range, ranges):  # map preserves order
            yield [Page(p, t) for p, t in part]


def parse_pdf(path: Path, filetype: str = "pdf") -> list[Page]:
    """All pages at once (used by tests and the eval)."""
    return [p for batch in parse_batches(path, filetype) for p in batch]

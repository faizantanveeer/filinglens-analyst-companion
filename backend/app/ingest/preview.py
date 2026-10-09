"""Render a document page as PNG, with the cited passage highlighted (cached on disk)."""

import hashlib
import re

import pymupdf

from .. import documents
from .parser import open_document


def _phrases(text: str, n: int = 6) -> list[str]:
    """Short, distinctive phrases from the chunk to search for on the page.

    The chunk is markdown (tables, emphasis) while the page has plain text, so we search for
    a handful of 5-word runs from prose lines and cells instead of the whole chunk.
    """
    plain = re.sub(r"[*_#`>|]+", " ", text)
    words = [w for w in plain.split() if not re.fullmatch(r"[-:.]+", w)]
    phrases, step = [], max(5, len(words) // n)
    for i in range(0, max(0, len(words) - 4), step):
        phrase = " ".join(words[i : i + 5])
        if len(phrase) >= 12:
            phrases.append(phrase)
    return phrases[:n]


def _as_pdf(doc_id: str, ftype: str) -> pymupdf.Document:
    """Highlights are PDF annotations. HTML/TXT/EPUB are laid out and converted to PDF once
    (same pagination as ingestion), cached next to the rendered pages."""
    if ftype == "pdf":
        return pymupdf.open(documents.file_path(doc_id, "pdf"))
    converted = documents.page_cache_dir(doc_id) / "document.pdf"
    if not converted.exists():
        with open_document(documents.file_path(doc_id, ftype), ftype) as source:
            converted.write_bytes(source.convert_to_pdf())
    return pymupdf.open(converted)


def render_page(doc_id: str, page: int, highlight: str = "", zoom: float = 1.6) -> bytes:
    """Page image for the source panel. Highlighting the cited text lets a reader verify a claim at a glance."""
    key = hashlib.sha1(f"{page}|{zoom}|{highlight}".encode()).hexdigest()[:16]
    cached = documents.page_cache_dir(doc_id) / f"{key}.png"
    if cached.exists():
        return cached.read_bytes()
    ftype = documents.filetype_of(doc_id)
    with _as_pdf(doc_id, ftype) as doc:
        if not 1 <= page <= doc.page_count:
            raise ValueError("page out of range")
        p = doc[page - 1]
        if highlight:
            for phrase in _phrases(highlight):
                for rect in p.search_for(phrase)[:3]:
                    annot = p.add_highlight_annot(rect)
                    annot.set_colors(stroke=(1.0, 0.85, 0.2))
                    annot.update()
        png = p.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("png")
    cached.write_bytes(png)
    return png

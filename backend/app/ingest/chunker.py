"""Structure-aware chunking: headings and paragraphs, tables never split."""

import re
from dataclasses import dataclass, field

from ..config import settings
from .parser import Page

HEADING = re.compile(r"^#{1,6}\s+(.*)$")
MIN_CHUNK_TOKENS = 10


def estimate_tokens(text: str) -> int:
    """~4 characters per token for English. Good enough for sizing chunks, and dependency-free."""
    return max(1, len(text) // 4)


@dataclass
class Block:
    text: str
    is_table: bool = False


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    page: int
    section_heading: str
    text: str
    has_table: bool = False
    suspicious: bool = False
    meta: dict = field(default_factory=dict)


def split_blocks(markdown: str) -> list[tuple[str, Block]]:
    """Split one page into (section_heading, block) pairs.

    Why: consecutive `|` lines form one table block, so a table can't be cut in half.
    Headings start a new section and are kept with the text below them.
    """
    out: list[tuple[str, Block]] = []
    heading = ""
    para: list[str] = []
    table: list[str] = []

    def flush_para():
        if para and "".join(para).strip():
            out.append((heading, Block("\n".join(para).strip())))
        para.clear()

    def flush_table():
        if table:
            out.append((heading, Block("\n".join(table).strip(), is_table=True)))
        table.clear()

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            flush_para()
            table.append(stripped)
            continue
        flush_table()
        m = HEADING.match(stripped)
        if m:
            flush_para()
            heading = re.sub(r"[*_`]", "", m.group(1)).strip()
            para.append(stripped)
        elif not stripped:
            flush_para()
        else:
            para.append(line)
    flush_para()
    flush_table()
    return out


def split_oversized(block: Block, budget: int) -> list[Block]:
    """Split a too-long paragraph at sentence ends. Tables are returned untouched."""
    if block.is_table or estimate_tokens(block.text) <= budget:
        return [block]
    parts, buf = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", block.text):
        if buf and estimate_tokens(buf + " " + sentence) > budget:
            parts.append(Block(buf.strip()))
            buf = ""
        buf += " " + sentence
    if buf.strip():
        parts.append(Block(buf.strip()))
    return parts


def overlap_tail(blocks: list[Block], budget: int) -> str:
    """The last sentences of the previous chunk, up to `budget` tokens. Tables are never carried
    (they'd be duplicated whole); if the chunk ends in a table there is no overlap."""
    if not blocks or blocks[-1].is_table:
        return ""
    tail = ""
    for sentence in reversed(re.split(r"(?<=[.!?])\s+", blocks[-1].text)):
        if tail and estimate_tokens(sentence + " " + tail) > budget:
            break
        tail = (sentence + " " + tail).strip()
    if estimate_tokens(tail) > budget:  # one very long sentence: keep its last words
        tail = tail[-budget * 4 :].split(" ", 1)[-1]
    return tail


def chunk_pages(doc_id: str, pages: list[Page], start: int = 0) -> list[Chunk]:
    """Pack blocks into ~chunk_tokens chunks per page, with ~15% overlap.

    Why per page: a chunk then has exactly one page to cite. Overlap carries the tail
    paragraphs of the previous chunk forward so a sentence near a boundary keeps context.
    Tables are never used as overlap (they'd be duplicated whole) and an oversized table
    becomes its own chunk rather than being split.
    """
    budget = settings.chunk_tokens
    overlap_budget = int(budget * settings.chunk_overlap)
    chunks: list[Chunk] = []

    for page in pages:
        current: list[Block] = []
        heading_for_chunk = ""

        def emit():
            if not current:
                return
            text = "\n\n".join(b.text for b in current)
            if estimate_tokens(text) < MIN_CHUNK_TOKENS:  # stray page numbers, lone headers
                return
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}:{start + len(chunks)}",  # unique across batches
                    doc_id=doc_id,
                    page=page.number,
                    section_heading=heading_for_chunk,
                    text=text,
                    has_table=any(b.is_table for b in current),
                )
            )

        fresh = 0  # blocks in `current` that aren't overlap carried from the previous chunk
        blocks = [(h, part) for h, b in split_blocks(page.markdown) for part in split_oversized(b, budget)]
        for heading, block in blocks:
            size = estimate_tokens(block.text)
            used = sum(estimate_tokens(b.text) for b in current)
            if current and used + size > budget:
                if fresh:
                    emit()
                    tail = overlap_tail(current, overlap_budget)
                    current = [Block(tail)] if tail else []
                else:
                    current = []  # only overlap so far and the next block won't fit: drop it
                fresh = 0
            if fresh == 0:
                heading_for_chunk = heading
            current.append(block)
            fresh += 1
        if fresh:
            emit()

    return chunks

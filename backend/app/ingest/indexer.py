"""Dense + BM25 sparse vectors → Qdrant (embedded, on-disk)."""

import threading
import uuid
from functools import lru_cache

from qdrant_client import QdrantClient, models

from ..config import settings
from ..embeddings import dense_dim, embed_documents, sparse_documents
from ..pipeline.guard_input import looks_like_injection
from .chunker import Chunk

# Local: bge-small (384-d). Cloud: Jina v3 at settings.jina_embedding_dim. Different vector spaces
# must never share a collection, so the name encodes the mode and dimension.
COLLECTION = f"chunks_jina{settings.jina_embedding_dim}" if settings.cloud else "chunks"

# Embedded Qdrant is a single local process; serialize access from FastAPI's thread pool.
qdrant_lock = threading.Lock()


@lru_cache(maxsize=1)
def client() -> QdrantClient:
    """Open (or create) the collection with named vectors `dense` and `sparse`.

    Local mode: embedded Qdrant on disk. Cloud mode: Qdrant Cloud over HTTPS (same client API).
    """
    if settings.cloud:
        qc = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30)
    else:
        settings.qdrant_path.mkdir(parents=True, exist_ok=True)
        qc = QdrantClient(path=str(settings.qdrant_path))
    if not qc.collection_exists(COLLECTION):
        qc.create_collection(
            COLLECTION,
            vectors_config={"dense": models.VectorParams(size=dense_dim(), distance=models.Distance.COSINE)},
            # BM25 needs IDF computed over the corpus; Qdrant does that with the IDF modifier.
            sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        if settings.cloud:
            qc.create_payload_index(COLLECTION, field_name="doc_id", field_schema=models.PayloadSchemaType.KEYWORD)
    return qc


def flag_suspicious(chunks: list[Chunk]) -> int:
    """Mark chunks that contain prompt-injection phrases.

    Why: an uploaded PDF is untrusted input. We keep the chunk (it may still hold facts)
    but flag it so the answer prompt and the UI can treat it with suspicion.
    """
    n = 0
    for c in chunks:
        if looks_like_injection(c.text):
            c.suspicious = True
            n += 1
    return n


def point_id(chunk_id: str) -> str:
    """Qdrant ids must be ints or UUIDs; derive a stable UUID from our readable chunk_id."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def index_chunks(chunks: list[Chunk], batch_size: int = 64) -> None:
    """Embed chunks (locally, or via Jina in cloud mode) and upsert them with their metadata."""
    qc = client()
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        texts = [c.text for c in batch]
        dense = embed_documents(texts)
        sparse = sparse_documents(texts)
        points = [
            models.PointStruct(
                id=point_id(c.chunk_id),
                vector={
                    "dense": d,
                    "sparse": models.SparseVector(indices=s[0], values=s[1]),
                },
                payload={
                    "chunk_id": c.chunk_id,
                    "doc_id": c.doc_id,
                    "page": c.page,
                    "section_heading": c.section_heading,
                    "text": c.text,
                    "has_table": c.has_table,
                    "suspicious": c.suspicious,
                },
            )
            for c, d, s in zip(batch, dense, sparse)
        ]
        with qdrant_lock:
            qc.upsert(COLLECTION, points=points)


def delete_document(doc_id: str) -> None:
    with qdrant_lock:
        client().delete(
            COLLECTION,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])
            ),
        )

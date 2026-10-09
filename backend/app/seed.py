"""Index the bundled sample report so a fresh deployment has something to ask about.

    python -m backend.app.seed            # download (if needed) and index the sample, marked protected

The public demo runs this at image build time: free Spaces have no persistent disk, so the
index is baked into the image instead of being rebuilt (slowly) after every restart.
"""

import logging
import sys
import urllib.request
from pathlib import Path

from . import documents
from .config import settings
from .db import tx

SAMPLE_NAME = "Berkshire Hathaway 2023 Annual Report.pdf"


def fetch_sample(dest: Path) -> Path:
    """Download the sample once. It's a public document, but not redistributed in the repo."""
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(settings.sample_document_url, headers={"User-Agent": "Mozilla/5.0 (FilingLens demo seed)"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        if not data.startswith(b"%PDF"):
            raise RuntimeError("Sample download did not return a PDF.")
        dest.write_bytes(data)
    return dest


def seed(pdf: Path) -> dict:
    data = pdf.read_bytes()
    digest = documents.sha256(data)
    existing = documents.find_by_hash(digest)
    if existing and existing["status"] == "ready":
        return existing
    doc_id = "sample"
    if existing:
        documents.delete(existing["id"])
    documents.register(doc_id, SAMPLE_NAME, digest, "pdf")
    documents.save_file(doc_id, "pdf", data)
    documents.ingest(doc_id)
    with tx() as c:
        c.execute("UPDATE documents SET protected = 1 WHERE id = ?", (doc_id,))
    return documents.get(doc_id)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else settings.data_dir / "sample" / "report.pdf"
    doc = seed(fetch_sample(target))
    print(f"Seeded: {doc['filename']} · {doc['pages']} pages · {doc['chunks']} chunks · status={doc['status']}")
    if doc["status"] != "ready":
        sys.exit(1)
    from .ingest.indexer import client

    client().close()  # embedded Qdrant: flush and release the lock before the build step ends

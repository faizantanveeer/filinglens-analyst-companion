import json
import time

import pymupdf
from fastapi.testclient import TestClient

from backend.app import documents, main
from backend.app.ingest import edgar
from backend.app.ingest.chunker import chunk_pages
from backend.app.ingest.parser import Page, filetype_for, parse_batches
from backend.app.schemas import AnswerJSON

client = TestClient(main.app)

HTML = b"""<!DOCTYPE html><html><body>
<h1>Acme Corp Annual Report 2024</h1>
<p>Revenue in 2024 was $1,250 million, compared with $1,000 million in 2023.</p>
<table><tr><th>Year</th><th>Revenue</th></tr><tr><td>2024</td><td>1,250</td></tr><tr><td>2023</td><td>1,000</td></tr></table>
</body></html>"""


def make_pdf(pages: int) -> bytes:
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"Page {i + 1}. Segment revenue was {100 + i} million dollars in fiscal 2024.")
    return doc.tobytes()


def wait_ready(doc_id: str, timeout: float = 120) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        d = documents.get(doc_id)
        if d["status"] != "processing":
            return d
        time.sleep(0.5)
    raise AssertionError("ingest timed out")


def test_supported_types_and_content_checks():
    assert filetype_for("10-K.HTM") == "html" and filetype_for("notes.md") == "txt" and filetype_for("x.docx") is None
    r = client.post("/documents", files={"file": ("report.docx", b"PK..", "application/octet-stream")})
    assert r.status_code == 415 and "Unsupported" in r.json()["detail"]
    r = client.post("/documents", files={"file": ("fake.pdf", b"<html>not a pdf</html>", "application/pdf")})
    assert r.status_code == 415  # extension says PDF, content says otherwise
    r = client.post("/documents", files={"file": ("bin.txt", b"\x00\x01\x02binary", "text/plain")})
    assert r.status_code == 415


def test_html_upload_is_parsed_and_indexed():
    r = client.post("/documents", files={"file": ("acme-10k.html", HTML, "text/html")})
    assert r.status_code == 202, r.text
    d = wait_ready(r.json()["id"])
    assert d["status"] == "ready" and d["filetype"] == "html" and d["chunks"] >= 1 and d["progress"] == 1


def test_parallel_batches_keep_order_and_unique_chunk_ids(tmp_path):
    path = tmp_path / "multi.pdf"
    path.write_bytes(make_pdf(7))
    batches = list(parse_batches(path, "pdf", workers=2, batch_pages=3))
    assert [len(b) for b in batches] == [3, 3, 1]
    assert [p.number for b in batches for p in b] == list(range(1, 8))
    ids, n = [], 0
    for b in batches:
        chunks = chunk_pages("d", b, start=n)
        ids += [c.chunk_id for c in chunks]
        n += len(chunks)
    assert len(ids) == len(set(ids)) == 7


def test_ingest_reports_progress_and_page_preview_highlights():
    r = client.post("/documents", files={"file": ("ten-pages.pdf", make_pdf(10), "application/pdf")})
    doc_id = r.json()["id"]
    d = wait_ready(doc_id)
    assert d["status"] == "ready" and d["pages"] == 10 and d["stage"] is None
    img = client.get(f"/documents/{doc_id}/pages/3.png", params={"highlight": "Segment revenue was 102 million dollars"})
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content[:4] == b"\x89PNG"
    assert client.get(f"/documents/{doc_id}/pages/99.png").status_code == 404
    assert client.get("/documents/nope/pages/1.png").status_code == 404


def test_edgar_import_uses_latest_form(monkeypatch):
    responses = {
        edgar.TICKERS_URL: json.dumps({"0": {"cik_str": 1234, "ticker": "ACME", "title": "Acme Corp"}}).encode(),
        edgar.SUBMISSIONS_URL.format(cik=1234): json.dumps(
            {"filings": {"recent": {"form": ["8-K", "10-K", "10-K"], "accessionNumber": ["a-1", "0001-24-01", "0001-23-01"],
                                    "primaryDocument": ["x.htm", "acme-2024.htm", "acme-2023.htm"],
                                    "reportDate": ["", "2024-12-31", "2023-12-31"], "filingDate": ["", "", ""]}}}
        ).encode(),
        edgar.ARCHIVE_URL.format(cik=1234, acc="00012401", doc="acme-2024.htm"): HTML.replace(b"Acme", b"Acme EDGAR"),
    }
    monkeypatch.setattr(edgar, "_tickers", {})
    monkeypatch.setattr(edgar, "_get", lambda url, timeout=30: responses[url])
    r = client.post("/documents/edgar", json={"ticker": "acme", "form": "10-K"})
    assert r.status_code == 202, r.text
    d = wait_ready(r.json()["id"])
    assert d["filename"] == "ACME 10-K 2024-12-31.html" and d["source_url"].endswith("acme-2024.htm") and d["status"] == "ready"
    assert client.post("/documents/edgar", json={"ticker": "NOPE"}).status_code == 502
    assert client.post("/documents/edgar", json={"ticker": "ACME; rm -rf"}).status_code == 422


def test_key_terms_never_carry_numbers():
    a = AnswerJSON.model_validate(
        {
            "answer": "x",
            "key_terms": [
                {"term": "Float", "definition": "Money an insurer holds between collecting premiums and paying claims."},
                {"term": "Leak", "definition": "Berkshire's float was 169 billion."},
                "not a dict",
            ],
        }
    )
    assert [k["term"] for k in a.key_terms] == ["Float"]

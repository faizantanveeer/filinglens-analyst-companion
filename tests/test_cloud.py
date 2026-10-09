"""Cloud-mode building blocks, tested without any network: BM25, the Postgres SQL adapter,
chunked uploads, the Vercel path fix and the slim LLM client."""

import pymupdf
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import documents, main
from backend.app.db import _PgConnection, _pg_schema, SCHEMA
from backend.app.llm import gateway
from backend.app.llm.gateway import LLMConfig
from backend.app.retrieval import bm25
from backend.app.serverless import RestorePath


def test_bm25_vectors_are_stable_and_skip_stopwords():
    idx, val = bm25.document_vector("The float of the insurance business grew; float matters.")
    assert len(idx) == len(set(idx)) and idx == sorted(idx)
    weights = dict(zip(idx, val))
    assert weights[bm25.term_id("float")] > weights[bm25.term_id("grew")]  # tf=2 beats tf=1
    assert bm25.term_id("the") not in weights  # stopword
    assert bm25.term_id("float") == bm25.term_id("float")  # stable across calls (crc32, not hash())
    q_idx, q_val = bm25.query_vector("What was Berkshire's EBITDA in FY2024?")
    assert set(q_val) == {1.0} and bm25.term_id("berkshire") in q_idx and bm25.term_id("fy2024") in q_idx


def test_postgres_adapter_translates_sqlite_style_sql():
    t = _PgConnection.translate
    assert t("SELECT * FROM s WHERE a = ? AND b LIKE ? ESCAPE '\\'") == "SELECT * FROM s WHERE a = %s AND b ILIKE %s ESCAPE '\\'"
    stmts = _pg_schema(SCHEMA)
    assert any("BIGSERIAL PRIMARY KEY" in s for s in stmts) and not any("AUTOINCREMENT" in s for s in stmts)
    assert any("BYTEA" in s for s in stmts) and all("--" not in s for s in stmts)


def test_chunked_upload_reassembles_pieces(monkeypatch):
    monkeypatch.setattr(documents, "PIECE", 512)  # force several pieces
    doc = pymupdf.open()
    for i in range(3):
        doc.new_page().insert_text((72, 72), f"Chunked upload page {i + 1}: revenue was {200 + i} million dollars.")
    data = doc.tobytes()
    assert len(data) > 3 * 512
    from conftest import user_headers

    client = TestClient(main.app)
    client.headers.update(user_headers(client, "cloud-uploader@example.com"))
    start = client.post("/uploads", json={"filename": "chunked.pdf", "size": len(data)}).json()
    size = start["chunk_size"]
    for seq, i in enumerate(range(0, len(data), size)):
        assert client.put(f"/uploads/{start['upload_id']}/{seq}", content=data[i : i + size]).status_code == 204
    r = client.post(f"/uploads/{start['upload_id']}/complete", json={"filename": "chunked.pdf"})
    assert r.status_code == 202, r.text
    assert documents.read_pieces(start["upload_id"]) == b""  # staging pieces cleaned up
    assert client.post("/uploads", json={"filename": "x.docx", "size": 10}).status_code == 415
    assert client.put("/uploads/../etc/0", content=b"x").status_code in (400, 404)


def test_restore_path_middleware():
    app = FastAPI()

    @app.get("/documents/{doc_id}/pages/{page}.png")
    def page(doc_id: str, page: int, highlight: str = ""):
        return {"doc": doc_id, "page": page, "highlight": highlight}

    app.add_middleware(RestorePath)
    c = TestClient(app)
    r = c.get("/api/index", params={"__path": "documents/abc/pages/3.png", "highlight": "net sales"})
    assert r.json() == {"doc": "abc", "page": 3, "highlight": "net sales"}


def test_slim_llm_client_uses_openai_compatible_endpoints(monkeypatch):
    calls = []

    class FakeCompletions:
        def create(self, **kw):
            calls.append(kw)

            class R:
                choices = [type("C", (), {"message": type("M", (), {"content": '{"ok": true}'})()})()]
                usage = type("U", (), {"prompt_tokens": 11, "completion_tokens": 3})()

            return R()

    class FakeClient:
        def __init__(self, **kw):
            calls.append(("client", kw))
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    import openai

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    monkeypatch.setattr(gateway, "litellm", None)
    r = gateway.complete("small", [{"role": "user", "content": "hi"}], LLMConfig("groq", "llama-3.1-8b-instant", "x", api_key="gsk-test-abcdefghijkl"), json_mode=True)
    assert r.text == '{"ok": true}' and r.input_tokens == 11 and r.cost == 0.0
    client_kw = calls[0][1]
    assert client_kw["base_url"] == "https://api.groq.com/openai/v1"
    assert calls[1]["model"] == "llama-3.1-8b-instant" and "max_tokens" in calls[1] and calls[1]["response_format"] == {"type": "json_object"}

    calls.clear()
    gateway.complete("large", [{"role": "user", "content": "hi"}], LLMConfig("openai", "s", "gpt-5", api_key="sk-test-abcdefghijklmnop"))
    assert calls[1]["model"] == "gpt-5" and "max_completion_tokens" in calls[1] and "max_tokens" not in calls[1]

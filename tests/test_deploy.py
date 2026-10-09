"""Public-deployment rules: CORS for the Vercel origin(s), protected sample, private Insights."""

import importlib

from fastapi.testclient import TestClient

from backend.app import documents, main
from backend.app.db import tx
from backend.app.obs.tracer import Trace


def test_cors_allows_vercel_production_and_previews_only(monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://filinglens.vercel.app")
    monkeypatch.setenv("FRONTEND_ORIGIN_REGEX", r"^https://filinglens(-[a-z0-9-]+)?\.vercel\.app$")
    from backend.app import config

    importlib.reload(config)
    reloaded = importlib.reload(main)
    try:
        c = TestClient(reloaded.app)

        def preflight(origin):
            r = c.options(
                "/chat",
                headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,x-llm-key,x-client-id"},
            )
            return r.status_code, r.headers.get("access-control-allow-origin")

        assert preflight("https://filinglens.vercel.app") == (200, "https://filinglens.vercel.app")
        assert preflight("https://filinglens-git-main-faizan.vercel.app")[0] == 200  # preview deployment
        assert preflight("https://evil.vercel.app")[0] == 400
        assert preflight("https://filinglens.vercel.app.evil.com")[0] == 400
    finally:
        monkeypatch.undo()
        importlib.reload(config)
        importlib.reload(main)


def test_sample_document_cannot_be_deleted():
    client = TestClient(main.app)
    documents.register("protected-1", "Sample.pdf", "hash-protected-1", "pdf")
    with tx() as c:
        c.execute("UPDATE documents SET protected = 1, status = 'ready' WHERE id = 'protected-1'")
    r = client.delete("/documents/protected-1")
    assert r.status_code == 403
    assert documents.get("protected-1") is not None
    assert next(d for d in client.get("/documents").json() if d["id"] == "protected-1")["protected"] is True


def test_insights_only_show_your_own_requests():
    client = TestClient(main.app)
    Trace(question="alice's private question", owner="client-alice-01", route="answer").save()
    Trace(question="bob's private question", owner="client-bob-0001", route="answer").save()
    alice = client.get("/insights", headers={"X-Client-Id": "client-alice-01"}).json()
    assert [r["question"] for r in alice["recent"]] == ["alice's private question"]
    assert client.get("/insights").json()["requests"] == 0  # no client id → nothing, not everything

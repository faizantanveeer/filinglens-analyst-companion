"""Authentication, RBAC, credits and data isolation."""

import hashlib

import pymupdf
from fastapi.testclient import TestClient

from backend.app import auth, documents, main
from backend.app.config import settings
from backend.app.db import tx
from conftest import guest_headers, user_headers

client = TestClient(main.app)
KEY = {"X-LLM-Key": "sk-test-1234567890abcdef"}
SETTINGS = {"provider": "openai", "small_model": "s", "large_model": "l", "use_cache": False}


def me(h):
    return client.get("/auth/me", headers=h).json()


def upload(h, name="doc.pdf", text="Private figure: 4242 million."):
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), text)
    data = d.tobytes()
    start = client.post("/uploads", json={"filename": name, "size": len(data)}, headers=h)
    if start.status_code != 201:
        return start
    up = start.json()["upload_id"]
    assert client.put(f"/uploads/{up}/0", content=data, headers=h).status_code == 204
    return client.post(f"/uploads/{up}/complete", json={"filename": name}, headers=h)


def test_everything_requires_a_session():
    for method, path in [("get", "/documents"), ("get", "/sessions"), ("get", "/memories"), ("get", "/insights"),
                         ("post", "/uploads"), ("get", "/auth/me"), ("get", "/documents/sample/pages/1.png")]:
        assert getattr(client, method)(path).status_code in (401, 422), path


def test_tokens_are_stored_hashed_and_revocable():
    r = client.post("/auth/guest").json()
    token = r["token"]
    with tx() as c:
        rows = [row["token_hash"] for row in c.execute("SELECT token_hash FROM auth_sessions").fetchall()]
    assert token not in rows and hashlib.sha256(token.encode()).hexdigest() in rows
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/auth/me", headers=h).status_code == 200
    assert client.post("/auth/logout", headers=h).status_code == 204
    assert client.get("/auth/me", headers=h).status_code == 401


def test_guest_trial_limits_then_asks_to_sign_up():
    g = guest_headers(client)
    info = me(g)
    assert info["is_guest"] and info["credits"]["limit"] == settings.guest_questions
    assert upload(g, "first.pdf").status_code == 202
    r = upload(g, "second.pdf", "Another document.")
    assert r.status_code == 402 and "account" in r.json()["detail"]  # one document in the trial
    with tx() as c:
        c.execute("UPDATE users SET questions_used = ? WHERE id = ?", (settings.guest_questions, info["id"]))
    r = client.post("/chat", json={"question": "What is the private figure?", "settings": SETTINGS}, headers={**g, **KEY})
    assert r.status_code == 402 and "free questions" in r.json()["detail"]


def test_signup_upgrades_guest_and_keeps_data():
    g = guest_headers(client)
    doc = upload(g, "trial.pdf").json()
    sid = client.post("/sessions", headers=g).json()["id"]
    r = client.post("/auth/signup", json={"email": "Upgrade@Example.com", "password": "Strong-Pass-123"}, headers=g)
    assert r.status_code == 201, r.text
    u = {"Authorization": f"Bearer {r.json()['token']}"}
    assert r.json()["user"]["email"] == "upgrade@example.com" and r.json()["user"]["role"] == "user"
    assert client.get("/auth/me", headers=g).status_code == 401  # guest token rotated out
    assert any(d["id"] == doc["id"] for d in client.get("/documents", headers=u).json())
    assert client.get(f"/sessions/{sid}", headers=u).status_code == 200


def test_login_merges_guest_data_into_existing_account():
    acct = user_headers(client, "merge@example.com")
    client.post("/auth/logout", headers=acct)
    g = guest_headers(client)
    doc = upload(g, "guest-doc.pdf").json()
    r = client.post("/auth/login", json={"email": "merge@example.com", "password": "Correct-Horse-9"}, headers=g)
    assert r.status_code == 200
    u = {"Authorization": f"Bearer {r.json()['token']}"}
    assert any(d["id"] == doc["id"] for d in client.get("/documents", headers=u).json())


def test_password_rules_generic_errors_and_rate_limit():
    assert client.post("/auth/signup", json={"email": "weak@example.com", "password": "short"}).status_code == 422
    assert client.post("/auth/signup", json={"email": "not-an-email", "password": "Strong-Pass-123"}).status_code == 422
    user_headers(client, "dupe@example.com")
    assert client.post("/auth/signup", json={"email": "dupe@example.com", "password": "Strong-Pass-123"}).status_code == 409
    wrong_pw = client.post("/auth/login", json={"email": "dupe@example.com", "password": "Wrong-Pass-123"})
    no_user = client.post("/auth/login", json={"email": "nobody@example.com", "password": "Wrong-Pass-123"})
    assert wrong_pw.status_code == no_user.status_code == 401 and wrong_pw.json() == no_user.json()  # no enumeration
    codes = [client.post("/auth/login", json={"email": "victim@example.com", "password": f"Guess-{i}-Pass"}).status_code
             for i in range(settings.login_attempts_per_15min + 1)]
    assert codes[-1] == 429


def test_users_cannot_see_each_others_documents():
    a, b = user_headers(client, "iso-a@example.com"), user_headers(client, "iso-b@example.com")
    doc = upload(a, "a-private.pdf").json()
    assert documents.get(doc["id"])["status"] == "ready"  # local mode indexes in a background task
    assert all(d["id"] != doc["id"] for d in client.get("/documents", headers=b).json())
    assert client.get(f"/documents/{doc['id']}/pages/1.png", headers=b).status_code == 404
    assert client.delete(f"/documents/{doc['id']}", headers=b).status_code == 404
    r = client.post("/chat", json={"question": "What is the private figure?", "doc_ids": [doc["id"]], "settings": SETTINGS}, headers={**b, **KEY})
    assert r.status_code == 400  # B's requested doc is filtered out; nothing else of A's is searchable
    # Same file uploaded by B becomes B's own copy, not a handle on A's document.
    doc_b = upload(b, "a-private.pdf").json()
    assert doc_b["id"] != doc["id"] and documents.get(doc_b["id"])["owner_id"] == me(b)["id"]
    # Upload pieces are bound to the user who started the upload.
    up = client.post("/uploads", json={"filename": "x.pdf", "size": 10}, headers=a).json()["upload_id"]
    assert client.put(f"/uploads/{up}/0", content=b"%PDF-1.4", headers=b).status_code == 404


def test_admin_routes_need_admin_role(monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "boss@example.com")
    user = user_headers(client, "regular@example.com")
    admin = user_headers(client, "boss@example.com")
    assert me(admin)["role"] == "admin"
    assert client.get("/admin/users", headers=user).status_code == 403
    assert client.get("/admin/users", headers=admin).status_code == 200
    assert client.post("/retrieve", json={"query": "revenue"}, headers=user).status_code == 403
    assert client.get("/insights", params={"scope": "all"}, headers=admin).status_code == 200


def test_password_hashing_roundtrip():
    h = auth.hash_password("Strong-Pass-123")
    assert h.startswith("scrypt$") and "Strong-Pass-123" not in h
    assert auth.verify_password("Strong-Pass-123", h) and not auth.verify_password("strong-pass-123", h)

"""Model lists come from the provider (filtered to chat models), and Groq's own "openai/..." names route to Groq."""

import urllib.error

from fastapi.testclient import TestClient

from backend.app.llm import models
from backend.app.llm.gateway import qualify
from backend.app.main import app
from conftest import guest_headers

client = TestClient(app)
SETTINGS = {"small_model": "x", "large_model": "y"}


def test_groq_gpt_oss_names_route_to_groq():
    assert qualify("openai/gpt-oss-120b", "groq") == "groq/openai/gpt-oss-120b"
    assert qualify("qwen/qwen3.8-27b", "groq") == "groq/qwen/qwen3.8-27b"
    assert qualify("gpt-5.6-luna", "openai") == "openai/gpt-5.6-luna"
    assert qualify("anthropic/claude-haiku-4-5", "openai") == "anthropic/claude-haiku-4-5"  # cross-provider fallback


def test_lists_only_chat_models_with_the_users_key(monkeypatch):
    seen = {}

    def fake(url, headers):
        seen.update(url=url, headers=headers)
        return {"data": [{"id": i} for i in ("gpt-5.6-terra", "gpt-5.6-luna", "text-embedding-3-large", "gpt-realtime", "whisper-1")]}

    monkeypatch.setattr(models, "_get_json", fake)
    h = {**guest_headers(client), "X-LLM-Key": "sk-test-key"}
    r = client.post("/settings/models", json={"settings": {**SETTINGS, "provider": "openai"}}, headers=h)
    assert r.json() == {"models": ["gpt-5.6-luna", "gpt-5.6-terra"]}
    assert seen["url"].startswith("https://api.openai.com/") and seen["headers"]["Authorization"] == "Bearer sk-test-key"


def test_rejected_key_gives_a_safe_message(monkeypatch):
    def fake(url, headers):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(models, "_get_json", fake)
    h = {**guest_headers(client), "X-LLM-Key": "gsk-secret"}
    body = client.post("/settings/models", json={"settings": {**SETTINGS, "provider": "groq"}}, headers=h).json()
    assert body["models"] == [] and "rejected" in body["message"] and "gsk-secret" not in body["message"]


def test_missing_key_and_azure():
    h = guest_headers(client)
    assert client.post("/settings/models", json={"settings": {**SETTINGS, "provider": "anthropic"}}, headers=h).status_code == 401
    assert client.post("/settings/models", json={"settings": {**SETTINGS, "provider": "azure"}}, headers=h).json() == {"models": []}

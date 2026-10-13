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


def test_json_is_found_after_reasoning_text():
    from backend.app.llm.gateway import parse_json

    assert parse_json('<think>The user wants {intent}. Maybe {"x": 1}?</think>\n{"intent": "chat"}') == {"intent": "chat"}
    assert parse_json('Sure! Here it is {see below}: {"reply": "Hi"}') == {"reply": "Hi"}


def test_reasoning_models_get_room_and_json_rejections_are_retried(monkeypatch):
    from backend.app.llm import gateway
    from backend.app.llm.gateway import LLMConfig, LLMResult

    calls = []

    def fake(model, key, messages, cap, json_mode, cfg):
        calls.append((model, cap, json_mode))
        if json_mode:
            raise RuntimeError("Error code: 400 - {'error': {'code': 'json_validate_failed'}}")
        return LLMResult('{"ok": true}', model, 1, 1, 0.0)

    monkeypatch.setattr(gateway, "_attempt", fake)
    r = gateway.complete("small", [{"role": "user", "content": "hi"}], LLMConfig("groq", "qwen/qwen3.8-27b", "x", api_key="gsk-test-abcdefghijkl"), json_mode=True, max_tokens=80)
    assert r.text == '{"ok": true}'
    assert calls == [("groq/qwen/qwen3.8-27b", 2048, True), ("groq/qwen/qwen3.8-27b", 2048, False)]
    calls.clear()
    gateway.complete("small", [{"role": "user", "content": "hi"}], LLMConfig("anthropic", "claude-haiku-4-5", "x", api_key="sk-ant-test-abcdefgh"), max_tokens=80)
    assert calls == [("anthropic/claude-haiku-4-5", 80, False)]  # non-reasoning models keep the small cap

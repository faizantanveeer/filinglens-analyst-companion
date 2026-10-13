"""Which chat models a provider key can use right now, straight from the provider's own model list.

Why: model names change every few months and old ones are shut down, so a hard-coded list goes
stale. The Settings page shows a curated list plus whatever this returns for the user's key.
Every host is fixed (no user-supplied URLs); Ollama uses the server's configured address.
"""

import json
import urllib.error
import urllib.request

from ..config import settings
from .gateway import mask

# Model families that aren't chat models (speech, images, embeddings, safety classifiers…).
NOT_CHAT = (
    "embed", "tts", "whisper", "transcribe", "audio", "realtime", "image", "dall-e", "sora", "moderation",
    "search", "guard", "safeguard", "orpheus", "playai", "imagen", "veo", "aqa", "live", "robotics",
    "computer-use", "codex", "instruct", "babbage", "davinci",
)


class ModelListError(Exception):
    pass


def _get_json(url: str, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "FinCite", **headers})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _fetch(provider: str, key: str | None) -> list[str]:
    if provider == "openai":
        data = _get_json("https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"})
        return [m["id"] for m in data.get("data", []) if m["id"].startswith(("gpt-", "o1", "o3", "o4", "chatgpt-"))]
    if provider == "anthropic":
        data = _get_json("https://api.anthropic.com/v1/models?limit=1000", {"x-api-key": key or "", "anthropic-version": "2023-06-01"})
        return [m["id"] for m in data.get("data", [])]
    if provider == "gemini":
        data = _get_json("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", {"x-goog-api-key": key or ""})
        return [
            m["name"].removeprefix("models/")
            for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", []) and m["name"].startswith("models/gemini")
        ]
    if provider == "groq":
        data = _get_json("https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {key}"})
        return [m["id"] for m in data.get("data", []) if m.get("active", True)]
    if provider == "ollama":
        data = _get_json(f"{settings.ollama_base_url.rstrip('/')}/api/tags", {})
        return [m["name"] for m in data.get("models", [])]
    return []  # Azure: deployment names are chosen by the user and can't be listed with an API key


def list_models(provider: str, key: str | None) -> list[str]:
    """Chat-capable model ids for this provider and key, sorted. Raises ModelListError with a safe message."""
    try:
        ids = _fetch(provider, key)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ModelListError("The provider rejected this API key.") from None
        raise ModelListError(f"The provider returned HTTP {exc.code}.") from None
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
        reason = "Ollama isn't reachable." if provider == "ollama" else "Couldn't reach the provider."
        raise ModelListError(f"{reason} ({mask(type(exc).__name__, [key or ''])})") from None
    # Ollama lists only what the user pulled (tags like "llama3.1:8b-instruct" are chat models).
    skip = ("embed",) if provider == "ollama" else NOT_CHAT
    return sorted({i for i in ids if not any(w in i.lower() for w in skip)})

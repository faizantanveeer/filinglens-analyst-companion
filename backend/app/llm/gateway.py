"""LiteLLM wrapper: model tiers, fallback chain, JSON mode, token/cost capture, key masking."""

import json
import re
import urllib.request
from dataclasses import dataclass

import litellm

from ..config import settings

# Never let LiteLLM print request details (which can include keys) or phone home.
litellm.suppress_debug_info = True
litellm.telemetry = False
litellm.drop_params = True  # silently drop params a provider doesn't support (e.g. response_format)

PROVIDERS = ("openai", "azure", "anthropic", "gemini", "groq", "ollama")


@dataclass
class LLMConfig:
    """Per-request LLM settings. Built from the request body + headers, never stored."""

    provider: str
    small_model: str
    large_model: str
    api_key: str | None = None
    fallback_model: str | None = None
    fallback_key: str | None = None
    azure_endpoint: str | None = None  # Azure OpenAI: https://<resource>.openai.azure.com
    azure_api_version: str | None = None

    def secrets(self) -> list[str]:
        return [k for k in (self.api_key, self.fallback_key) if k]


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost: float


class LLMError(Exception):
    pass


def mask(text: str, secrets: list[str]) -> str:
    """Remove keys from any string that might reach a log, trace or the UI (provider errors echo them)."""
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return re.sub(r"\b(sk|gsk|AIza)[-_A-Za-z0-9]{12,}", "***", text)


def qualify(model: str, provider: str) -> str:
    """LiteLLM routes by prefix: 'anthropic/claude-haiku-4-5'. Accept bare names from Settings."""
    if any(model.startswith(f"{p}/") for p in PROVIDERS):
        return model
    return f"{provider}/{model}"


def ollama_running() -> bool:
    try:
        with urllib.request.urlopen(f"{settings.ollama_base_url}/api/tags", timeout=0.5):
            return True
    except Exception:
        return False


def _chain(tier: str, cfg: LLMConfig) -> list[tuple[str, str | None]]:
    """[(model, key)]: primary → user's fallback → local Ollama (only if running)."""
    primary = cfg.small_model if tier == "small" else cfg.large_model
    chain = [(qualify(primary, cfg.provider), cfg.api_key)]
    if cfg.fallback_model:
        fb = qualify(cfg.fallback_model, cfg.provider)
        same_provider = fb.split("/", 1)[0] == cfg.provider
        chain.append((fb, cfg.api_key if same_provider else cfg.fallback_key))
    if settings.ollama_fallback_model and ollama_running():
        chain.append((qualify(settings.ollama_fallback_model, "ollama"), None))
    return chain


def complete(tier: str, messages: list[dict], cfg: LLMConfig, json_mode: bool = False, max_tokens: int | None = None) -> LLMResult:
    """One chat completion with fallbacks.

    Why one function: every LLM call in the pipeline goes through here, so tiers, caps,
    fallbacks and cost accounting are consistent and the key handling is in one place.
    """
    cap = max_tokens or (settings.max_tokens_small if tier == "small" else settings.max_tokens_large)
    errors = []
    for model, key in _chain(tier, cfg):
        kwargs: dict = {"model": model, "messages": messages, "max_tokens": cap, "timeout": 60, "num_retries": 0}
        if model.startswith("ollama/"):
            kwargs["api_base"] = settings.ollama_base_url  # local, no key
        elif not key:
            errors.append(f"{model}: no API key")
            continue
        elif model.startswith("azure/"):
            # Azure OpenAI: "model" is the deployment name; the resource endpoint and API version are required.
            if not cfg.azure_endpoint:
                errors.append(f"{model}: no Azure endpoint set")
                continue
            kwargs.update(api_key=key, api_base=cfg.azure_endpoint, api_version=cfg.azure_api_version)
        else:
            kwargs["api_key"] = key
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = litellm.completion(**kwargs)
        except Exception as exc:
            errors.append(f"{model}: {type(exc).__name__}: {mask(str(exc), cfg.secrets())[:200]}")
            continue
        usage = getattr(resp, "usage", None)
        try:
            cost = float(litellm.completion_cost(completion_response=resp) or 0.0)
        except Exception:
            cost = 0.0  # unknown pricing (e.g. Ollama or a brand-new model)
        return LLMResult(
            text=resp.choices[0].message.content or "",
            model=model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            cost=cost,
        )
    raise LLMError("All models failed. " + " | ".join(errors))


def parse_json(text: str) -> dict:
    """Extract the JSON object from a reply (some models wrap it in prose or ``` fences)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start : end + 1])

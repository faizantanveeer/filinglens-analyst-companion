"""LiteLLM wrapper: model tiers, fallback chain, JSON mode, token/cost capture, key masking."""

import json
import re
import urllib.request
from dataclasses import dataclass

from ..config import settings

# LiteLLM (local installs) gives one interface plus cost accounting, but it's ~160 MB. The serverless
# bundle omits it, and calls go through each provider's OpenAI-compatible endpoint with the slim
# `openai` SDK instead (see _call_openai_compatible). Cost then isn't tracked (reported as 0).
try:
    import litellm

    # Never let LiteLLM print request details (which can include keys) or phone home.
    litellm.suppress_debug_info = True
    litellm.telemetry = False
    litellm.drop_params = True  # silently drop params a provider doesn't support (e.g. response_format)
except ImportError:  # cloud / serverless bundle
    litellm = None

# OpenAI-compatible endpoints for the slim path.
COMPAT_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "anthropic": "https://api.anthropic.com/v1/",
}
JSON_MODE_PROVIDERS = {"openai", "azure", "groq", "gemini", "ollama"}  # Anthropic's compat layer ignores it

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


# List prices in USD per million tokens (input, output), used when LiteLLM isn't installed (cloud mode)
# or doesn't know the model. Longest matching prefix wins; unknown models cost 0. Estimates only.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-haiku": (1.00, 5.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-opus": (5.00, 25.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "llama-3.1-8b": (0.05, 0.08),
    "llama-3.3-70b": (0.59, 0.79),
}


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    name = model.split("/", 1)[-1].lower()
    match = max((p for p in PRICES if name.startswith(p)), key=len, default=None)
    if not match:
        return 0.0
    p_in, p_out = PRICES[match]
    return (tokens_in * p_in + tokens_out * p_out) / 1_000_000


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


def _call_openai_compatible(model: str, key: str | None, messages: list[dict], cap: int, json_mode: bool, cfg: LLMConfig):
    """One completion via the `openai` SDK against the provider's OpenAI-compatible API.
    Returns (text, input_tokens, output_tokens)."""
    import openai

    provider, name = model.split("/", 1)
    if provider == "azure":
        client = openai.AzureOpenAI(api_key=key, azure_endpoint=cfg.azure_endpoint, api_version=cfg.azure_api_version, timeout=60, max_retries=0)
    elif provider == "ollama":
        client = openai.OpenAI(api_key="ollama", base_url=f"{settings.ollama_base_url.rstrip('/')}/v1", timeout=60, max_retries=0)
    else:
        client = openai.OpenAI(api_key=key, base_url=COMPAT_BASE_URLS.get(provider), timeout=60, max_retries=0)
    kwargs: dict = {"model": name, "messages": messages}
    # OpenAI's newer models (gpt-5, o-series) reject max_tokens in favour of max_completion_tokens.
    kwargs["max_completion_tokens" if provider in ("openai", "azure") else "max_tokens"] = cap
    if json_mode and provider in JSON_MODE_PROVIDERS:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    usage = resp.usage
    return resp.choices[0].message.content or "", getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0


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
        if litellm is None:
            try:
                text, tokens_in, tokens_out = _call_openai_compatible(model, key, messages, cap, json_mode, cfg)
            except Exception as exc:
                errors.append(f"{model}: {type(exc).__name__}: {mask(str(exc), cfg.secrets())[:200]}")
                continue
            cost = estimate_cost(model, tokens_in, tokens_out)
            return LLMResult(text=text, model=model, input_tokens=tokens_in, output_tokens=tokens_out, cost=cost)
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
        cost = cost or estimate_cost(model, getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0)
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

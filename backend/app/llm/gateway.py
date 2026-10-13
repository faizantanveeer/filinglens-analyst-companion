"""LiteLLM wrapper: model tiers, fallback chain, JSON mode, token/cost capture, key masking."""

import json
import re
import urllib.request
from dataclasses import dataclass

from ..config import settings

# LiteLLM (local installs) gives one interface plus cost accounting, but it's ~160 MB. The serverless
# bundle omits it, and calls go through each provider's OpenAI-compatible endpoint with the slim
# `openai` SDK instead (see _call_openai_compatible). Cost then comes from the PRICES table below.
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
    "gpt-5.6-sol": (4.00, 20.00),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    "claude-haiku-5": (0.10, 0.50),
    "claude-haiku": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus": (5.00, 25.00),
    "claude-fable": (10.00, 50.00),
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
    """LiteLLM routes by prefix: 'anthropic/claude-haiku-4-5'. Accept bare names from Settings.

    Groq names some of its own models "openai/gpt-oss-120b"; on Groq that's a model name, not a
    request to route to OpenAI.
    """
    if provider == "groq" and model.startswith("openai/gpt-oss"):
        return f"groq/{model}"
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


# Reasoning models think before they answer, and the thinking counts against max_tokens. With the small caps
# used for routing or rewriting, they can run out before writing any JSON, so they get a higher floor.
# It's a ceiling, not a cost: only tokens actually generated are billed.
REASONING = re.compile(r"gpt-oss|qwen3|deepseek-r1|gpt-5|gpt-6|(^|/)o[134](-|$)|gemini-(2\.5|3)", re.I)
REASONING_MIN_TOKENS = 2048
# Some providers (Groq) reject a reply that isn't valid JSON when JSON mode is on, instead of returning it.
# The prompts ask for JSON anyway and parse_json() extracts it, so retry once without JSON mode.
JSON_REJECTED = re.compile(r"json_validate_failed|failed to generate json|failed_generation", re.I)


def _attempt(model: str, key: str | None, messages: list[dict], cap: int, json_mode: bool, cfg: LLMConfig) -> LLMResult:
    """One call to one model. Raises on any provider error."""
    if litellm is None:
        text, tokens_in, tokens_out = _call_openai_compatible(model, key, messages, cap, json_mode, cfg)
        return LLMResult(text=text, model=model, input_tokens=tokens_in, output_tokens=tokens_out, cost=estimate_cost(model, tokens_in, tokens_out))
    kwargs: dict = {"model": model, "messages": messages, "max_tokens": cap, "timeout": 60, "num_retries": 0}
    if model.startswith("ollama/"):
        kwargs["api_base"] = settings.ollama_base_url  # local, no key
    elif model.startswith("azure/"):
        # Azure OpenAI: "model" is the deployment name; the resource endpoint and API version are required.
        kwargs.update(api_key=key, api_base=cfg.azure_endpoint, api_version=cfg.azure_api_version)
    else:
        kwargs["api_key"] = key
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = litellm.completion(**kwargs)
    usage = getattr(resp, "usage", None)
    tokens_in, tokens_out = getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0
    try:
        cost = float(litellm.completion_cost(completion_response=resp) or 0.0)
    except Exception:
        cost = 0.0  # unknown pricing (e.g. Ollama or a brand-new model)
    return LLMResult(
        text=resp.choices[0].message.content or "",
        model=model,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        cost=cost or estimate_cost(model, tokens_in, tokens_out),
    )


def complete(tier: str, messages: list[dict], cfg: LLMConfig, json_mode: bool = False, max_tokens: int | None = None) -> LLMResult:
    """One chat completion with fallbacks.

    Why one function: every LLM call in the pipeline goes through here, so tiers, caps,
    fallbacks and cost accounting are consistent and the key handling is in one place.
    """
    cap = max_tokens or (settings.max_tokens_small if tier == "small" else settings.max_tokens_large)
    errors = []
    for model, key in _chain(tier, cfg):
        if not model.startswith("ollama/") and not key:
            errors.append(f"{model}: no API key")
            continue
        if model.startswith("azure/") and not cfg.azure_endpoint:
            errors.append(f"{model}: no Azure endpoint set")
            continue
        model_cap = max(cap, REASONING_MIN_TOKENS) if REASONING.search(model) else cap
        for use_json in [json_mode, False] if json_mode else [False]:
            try:
                return _attempt(model, key, messages, model_cap, use_json, cfg)
            except Exception as exc:
                message = mask(str(exc), cfg.secrets())
                if use_json and JSON_REJECTED.search(message):
                    continue  # same model again, without JSON mode
                errors.append(f"{model}: {type(exc).__name__}: {message[:200]}")
                break
    raise LLMError("All models failed. " + " | ".join(errors))


THINKING = re.compile(r"<think>.*?(</think>|$)", re.S | re.I)


def parse_json(text: str) -> dict:
    """Extract the JSON object from a reply. Models wrap it in prose or ``` fences, and reasoning models
    may put their thinking (which can contain braces) in <think>…</think> before it."""
    text = THINKING.sub("", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    try:
        return json.loads(text[start : end + 1])
    except ValueError:
        pass
    # Several brace groups (e.g. prose with {curly} words before the answer): take the last complete object.
    decoder, found = json.JSONDecoder(), None
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(text, i)
            except ValueError:
                continue
            if isinstance(obj, dict):
                found = obj
    if found is None:
        raise ValueError("no JSON object in reply")
    return found

"""Pydantic request/response models."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

Provider = Literal["openai", "azure", "anthropic", "gemini", "groq", "ollama"]

# Azure OpenAI resources live on these domains. Anything else is rejected so the server can't be
# pointed at an arbitrary URL (which would also send the user's key there).
AZURE_HOST_SUFFIXES = (".openai.azure.com", ".cognitiveservices.azure.com", ".services.ai.azure.com")


class LLMSettings(BaseModel):
    """Non-secret settings sent with each request. The key travels separately in X-LLM-Key."""

    provider: Provider = "openai"
    small_model: str = Field(min_length=1, max_length=120)
    large_model: str = Field(min_length=1, max_length=120)
    fallback_model: str | None = Field(default=None, max_length=120)
    # Azure OpenAI only: models are deployment names; endpoint and API version are required.
    azure_endpoint: str | None = Field(default=None, max_length=300)
    azure_api_version: str = Field(default="2024-10-21", max_length=40)
    top_k: int = Field(default=5, ge=1, le=10)
    use_cache: bool = True
    use_guardrails: bool = True
    use_judge: bool = False
    use_web_search: bool = True  # only used when the documents can't answer; needs X-Search-Key
    use_memory: bool = False  # cross-chat memory (opt-in)
    explain_terms: bool = True  # plain-English "key terms" box under answers
    token_budget_remaining: int | None = None

    @field_validator("azure_endpoint")
    @classmethod
    def _azure_endpoint(cls, v: str | None) -> str | None:
        if not v or not v.strip():
            return None
        parts = urlsplit(v.strip())
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host.endswith(AZURE_HOST_SUFFIXES):
            raise ValueError("Azure endpoint must look like https://<resource>.openai.azure.com")
        return f"https://{host}"


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=20000)  # hard cap; the guardrail limit is lower
    history: list[Turn] = Field(default_factory=list, max_length=40)
    doc_ids: list[str] | None = None
    deep: bool = False  # Deep research: sub-questions, more context, structured answer
    session_id: str | None = Field(default=None, max_length=40)  # history is loaded server-side when set
    settings: LLMSettings


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UploadStart(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    size: int = Field(ge=1)


class UploadComplete(BaseModel):
    filename: str = Field(min_length=1, max_length=200)


class EdgarImportRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=10, pattern=r"^[A-Za-z.\-]+$")
    form: Literal["10-K", "10-Q", "20-F", "40-F"] = "10-K"


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ValidateRequest(BaseModel):
    settings: LLMSettings


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    doc_ids: list[str] | None = None


class DocumentOut(BaseModel):
    id: str
    filename: str
    status: Literal["processing", "ready", "error"]
    pages: int
    chunks: int
    suspicious_chunks: int
    error: str | None = None
    created_at: str
    filetype: str | None = "pdf"
    progress: float | None = 0
    stage: str | None = None
    source_url: str | None = None
    protected: bool | None = False
    owner_id: str | None = None


class AnswerJSON(BaseModel):
    """The shape the answer model must return. Validated; invalid output gets one retry."""

    answer: str
    citations: list[str] = Field(default_factory=list)
    unanswerable: bool = False
    follow_ups: list[str] = Field(default_factory=list)
    key_terms: list[dict] = Field(default_factory=list)

    @field_validator("key_terms", mode="before")
    @classmethod
    def _key_terms(cls, v) -> list[dict]:
        """Plain-English definitions use general knowledge, so they must never smuggle in figures:
        any definition with a digit is dropped (numbers only ever come from cited sources)."""
        out = []
        for item in v if isinstance(v, list) else []:
            if not isinstance(item, dict):
                continue
            term = " ".join(str(item.get("term", "")).split())[:60]
            definition = " ".join(str(item.get("definition", "")).split())[:240]
            if term and definition and not any(ch.isdigit() for ch in definition):
                out.append({"term": term, "definition": definition})
        return out[:4]

    @field_validator("follow_ups")
    @classmethod
    def _follow_ups(cls, v: list[str]) -> list[str]:
        """Keep at most 3 short, distinct questions; never fail the whole answer over them."""
        out = []
        for q in v:
            q = " ".join(str(q).split())[:160]
            if q and q.lower() not in (o.lower() for o in out):
                out.append(q)
        return out[:3]


class RouteJSON(BaseModel):
    intent: Literal["lookup", "compare", "summarize", "out_of_scope"]
    needs_calc: bool = False
    needs_chart: bool = False
    complexity: Literal["low", "high"] = "high"

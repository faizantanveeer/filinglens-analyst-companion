"""Central defaults. Values come from environment / .env so nothing is hard-coded per deploy."""

import socket
from pathlib import Path
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


def local_ipv4_addresses() -> list[str]:
    """This machine's own non-loopback IPv4 addresses."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return sorted({i[4][0] for i in infos if not i[4][0].startswith("127.")})


class Settings(BaseSettings):
    """App settings. Never put API keys here: user keys arrive per request (X-LLM-Key)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "FilingLens"
    # The only browser origin allowed to call the API (CORS). Comma-separated for multiple.
    frontend_origin: str = "http://localhost:3000"
    # Optional regex for extra origins, e.g. Vercel preview deployments of *this* project:
    # ^https://filinglens(-[a-z0-9-]+)?\.vercel\.app$
    frontend_origin_regex: str = ""

    # Public-demo hardening
    sample_document_url: str = "https://www.berkshirehathaway.com/2023ar/2023ar.pdf"

    # Storage
    data_dir: Path = Path("data")
    max_upload_mb: int = 50

    # Ingestion: page-parallel parsing (CPU-bound), overlapped with embedding
    parse_workers: int = 4
    parse_batch_pages: int = 16

    # SEC EDGAR import. The SEC requires a descriptive User-Agent with contact details:
    # set SEC_USER_AGENT="YourApp your.email@example.com" in .env.
    sec_user_agent: str = "FilingLens research tool admin@example.com"

    # Chunking: ~500 tokens with ~15% overlap (tokens estimated as chars / 4).
    chunk_tokens: int = 500
    chunk_overlap: float = 0.15

    # Local models (fastembed): no API tokens spent on indexing or reranking.
    dense_model: str = "BAAI/bge-small-en-v1.5"
    sparse_model: str = "Qdrant/bm25"
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"

    # Retrieval
    candidates_per_retriever: int = 20  # top N from dense and from BM25 each
    rrf_k: int = 60
    # Fused candidates sent to the cross-encoder. Measured on the eval set (see eval/results.md):
    # 20 → 10 cut rerank latency ~2.4x (2.5 s → 1.0 s on this CPU) and lifted Hit@5 0.88 → 0.94,
    # because the relevant chunk was always within RRF rank 8 and extra weak candidates only gave
    # the cross-encoder more chances to promote a wrong one.
    rerank_pool: int = 10
    top_k: int = 5  # chunks kept after rerank (user can override per request)
    # Cross-encoder logit below which we abstain. Tuned in Phase 7 (see eval/results.md).
    min_rerank_score: float = 0.0

    # Guardrails
    max_question_chars: int = 1000

    # Generation caps (keep cost bounded even with a large model)
    max_tokens_small: int = 700
    max_tokens_large: int = 1200
    max_tokens_deep: int = 2200

    # Deep research
    deep_sub_questions: int = 4
    deep_chunks_per_sub_question: int = 4
    deep_max_chunks: int = 10

    # Web search (Tavily): only when the documents can't answer
    web_results: int = 5

    # Cache
    cache_similarity: float = 0.95

    # Conversation context (long chats): last N turns verbatim, older turns folded into a summary
    context_recent_turns: int = 4
    context_fold_batch_turns: int = 2  # fold older turns into the summary in batches of this size
    context_turn_chars: int = 600  # each turn is trimmed to this before it reaches a prompt
    summary_max_words: int = 150

    # Cross-chat memory (opt-in per request)
    memory_max_per_owner: int = 50
    memory_top_k: int = 3
    memory_min_similarity: float = 0.5
    memory_dedupe_similarity: float = 0.9

    # Optional last-resort fallback: a local Ollama model, used only if Ollama is reachable.
    ollama_base_url: str = "http://localhost:11434"
    ollama_fallback_model: str = ""  # e.g. "llama3.1"; empty disables

    @property
    def cors_origins(self) -> list[str]:
        """FRONTEND_ORIGIN, plus this machine's own LAN addresses for any localhost origin.

        Why: opening the dev UI through its "Network" URL (http://192.168.x.x:3000) is a
        different origin from localhost. Only this machine's own IPs are added, so other hosts
        stay blocked.
        """
        origins = [o.strip().rstrip("/") for o in self.frontend_origin.split(",") if o.strip()]
        extra = []
        for o in origins:
            parsed = urlsplit(o)
            if parsed.hostname in ("localhost", "127.0.0.1"):
                port = f":{parsed.port}" if parsed.port else ""
                extra += [f"{parsed.scheme}://{ip}{port}" for ip in local_ipv4_addresses()]
        return list(dict.fromkeys(origins + extra))

    @property
    def qdrant_path(self) -> Path:
        return self.data_dir / "qdrant"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "filinglens.db"


settings = Settings()

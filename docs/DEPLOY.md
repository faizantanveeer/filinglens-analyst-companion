# Deployment: everything on Vercel (cloud mode)

```
Browser ──▶ filinglens-analyst-companion.vercel.app   (Next.js, root dir: frontend/)
   └──────▶ filinglens-api.vercel.app                 (FastAPI as a Python function, repo root: api/index.py)
                ├─ Neon Postgres     documents, file pieces, sessions, memory, cache, traces
                ├─ Qdrant Cloud      dense + BM25 sparse vectors (collection chunks_jina512)
                └─ Jina AI           embeddings (jina-embeddings-v3, 512-d) + reranking (jina-reranker-v2)
```

**Why cloud mode exists:** the local stack (LiteLLM, onnxruntime, fastembed models) is about 808 MB and needs a persistent disk.
Vercel functions are small, short-lived and have no disk, so cloud mode swaps in hosted services:

| Local mode | Cloud mode |
|---|---|
| SQLite | Postgres (`DATABASE_URL`, Neon free tier) |
| Embedded Qdrant on disk | Qdrant Cloud (`QDRANT_URL`, `QDRANT_API_KEY`) |
| fastembed models (bge-small, BM25, MiniLM) | Jina API (`JINA_API_KEY`) + pure-Python BM25 |
| LiteLLM | Slim OpenAI-compatible client (`openai` SDK) |
| Files on disk, background indexing | Files in Postgres; indexing inside the request (≤ 300 s) |

Cloud mode only switches on with `DEPLOY_MODE=cloud`, so credentials in a local `.env` never redirect a local run.
Measured on Vercel (probe): SSE streams live, 300 s requests work, parsing runs at 0.52 s/page (152 pages ≈ 80 s).

**Retrieval numbers differ by mode.** Local-mode results (`eval/results.md`) don't carry over to cloud mode. The
cloud rerank threshold (`MIN_RERANK_SCORE=0.1`, Jina's 0–1 scale) still needs tuning: run
`DEPLOY_MODE=cloud python eval/run_eval.py` → `eval/results-cloud.md`.

## Projects and settings

**`filinglens-api`** (Vercel project, root = repo root, no framework). `vercel.json` rewrites every path to
`/api/index?__path=…` and `backend/app/serverless.py` restores it. Environment variables:
- **Mode and runtime:** `DEPLOY_MODE=cloud`, `DATA_DIR=/tmp/filinglens`, `PARSE_WORKERS=1`, `MAX_UPLOAD_MB=20`, `MIN_RERANK_SCORE=0.1`
- **CORS:** `FRONTEND_ORIGIN=https://filinglens-analyst-companion.vercel.app`, and `FRONTEND_ORIGIN_REGEX` for this project's preview URLs
- **SEC:** `SEC_USER_AGENT`
- **Secrets (stored as *sensitive*):** `DATABASE_URL`, `QDRANT_URL`, `QDRANT_API_KEY`, `JINA_API_KEY`

**`filinglens-analyst-companion`** (Next.js, root dir `frontend`): `NEXT_PUBLIC_API_URL=https://filinglens-api.vercel.app`.

`.vercelignore` at the repo root applies to **both** projects, so it must never exclude `frontend/`.

## Releasing

- **Branches:** work on `dev` (every push gets preview URLs); merge `dev` → `main` to deploy production. Both projects rebuild.
- **Sample document:** it's already indexed in the cloud services. To re-seed, run
  `DEPLOY_MODE=cloud PARSE_WORKERS=1 DATA_DIR=/tmp/fl python -m backend.app.seed eval/data/report.pdf`, with the cloud credentials in `.env`.
- **Uploads:** the browser sends files in ≤ 4 MB pieces (`/uploads/...`) to stay under Vercel's 4.5 MB request limit.

## Other hosting options (kept, not active)

- **Docker:** `Dockerfile.backend` / `docker-compose.yml` run local mode anywhere.
- **Hugging Face Spaces** (`deploy/huggingface`, `deploy/push_space.py`): Docker Spaces on CPU now require PRO.
- **Modal** (`deploy/modal_app.py`): needs a payment method before the free credits apply.

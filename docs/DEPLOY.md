# Deployment: everything on Vercel (cloud mode)

```
Browser ──▶ fincite.vercel.app        (Next.js, root dir: frontend/)
   └──────▶ fincite-api.vercel.app    (FastAPI as a Python function, repo root: api/index.py)
                ├─ Neon Postgres     users, auth sessions, documents, file pieces, chats, memory, cache, traces
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
| LiteLLM (`requirements-local.txt`) | Slim OpenAI-compatible client (`openai` SDK, `requirements.txt` only) |
| Files on disk, background indexing | Files in Postgres; indexing inside the request (≤ 300 s) |
| Summaries and memories in a background thread | Run inside the request after the `done` event |

Cloud mode only switches on with `DEPLOY_MODE=cloud`, so credentials in a local `.env` never redirect a local run.
`api/index.py` sets `DEPLOY_MODE=cloud`, `DATA_DIR=/tmp/fincite` and `PARSE_WORKERS=1` as defaults.
Measured on Vercel (probe): SSE streams live, 300 s requests work, parsing runs at 0.52 s/page (152 pages ≈ 80 s).

**Retrieval numbers differ by mode.** Local-mode results (`eval/results.md`) don't carry over to cloud mode. The
cloud rerank threshold (`MIN_RERANK_SCORE=0.1`, Jina's 0–1 scale) still needs tuning: run
`DEPLOY_MODE=cloud python eval/run_eval.py` → `eval/results-cloud.md`.

## Projects and settings

**`fincite-api`** (Vercel project, root = repo root, no framework). `vercel.json` gives `api/index.py` a 300 s limit
and rewrites every path to `/api/index?__path=…`; `backend/app/serverless.py` restores the original path. Environment variables:
- **Mode and runtime:** `DEPLOY_MODE=cloud`, `DATA_DIR=/tmp/fincite`, `PARSE_WORKERS=1`, `MAX_UPLOAD_MB=20`, `MIN_RERANK_SCORE=0.1`
- **CORS:** `FRONTEND_ORIGIN=https://fincite.vercel.app`, and `FRONTEND_ORIGIN_REGEX=^https://fincite(-[a-z0-9-]+)?\.vercel\.app$` for preview URLs
- **Secrets (stored as *sensitive*):** `DATABASE_URL`, `QDRANT_URL`, `QDRANT_API_KEY`, `JINA_API_KEY`
- **Accounts:** `ADMIN_EMAILS` (comma-separated; these accounts get the admin role on sign-up or log-in). Optional overrides: `GUEST_QUESTIONS`, `USER_QUESTIONS_PER_MONTH`, `USER_DOCUMENTS`, …

**`fincite`** (Next.js, root dir `frontend`): `NEXT_PUBLIC_API_URL=https://fincite-api.vercel.app`. It's inlined at
build time, so redeploy the frontend after changing it. The production CSP allows `connect-src` to this URL only.

`.vercelignore` at the repo root applies to **both** projects, so it must never exclude `frontend/`.

## Releasing

- **Branches:** work on `dev` (every push gets preview URLs); merge `dev` → `main` to deploy production. Both projects rebuild.
- **`main` is protected:** open a pull request from `dev` and merge it to release.
- **Sample document:** it's already indexed in the cloud services. To re-seed, run
  `DEPLOY_MODE=cloud PARSE_WORKERS=1 DATA_DIR=/tmp/fc python -m backend.app.seed eval/data/report.pdf`, with the cloud credentials in `.env`.
- **Uploads:** the browser sends files in ≤ 4 MB pieces (`/uploads/...`) to stay under Vercel's 4.5 MB request limit.
- **Schema changes** (new columns such as `sessions.pinned`) are applied automatically when the API starts; there's no migration step.

## Running outside Vercel

Vercel is the only hosting in use. To run local mode in containers instead, `docker compose up --build` uses
the two targets of the single `Dockerfile` (see the README).

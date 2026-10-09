# FilingLens

Grounded Q&A over company annual reports and SEC filings. Upload a report (or import one from SEC EDGAR by ticker), ask questions in plain English, and get answers that cite their page. Numbers are calculated in Python, not by the LLM. When the documents don't support an answer, it says "Not found in the provided documents" instead of guessing.

## Architecture

```mermaid
flowchart TD
    Q[Question] --> G[Input guardrails: length, injection, PII redaction]
    G -->|blocked| R0[Refusal, 0 tokens]
    G --> RW[Rewrite follow-up → standalone query · small model]
    RW --> C{Semantic cache ≥ 0.95?}
    C -->|hit| OUT[Cached answer, 0 tokens]
    C -->|miss| RT[Router · small model JSON → tier]
    RT -->|out_of_scope| R1[Scope message]
    RT --> RET[Hybrid retrieval: dense + BM25 → RRF k=60]
    RET --> RR[Cross-encoder rerank → top_k]
    RR -->|best score < MIN_RERANK_SCORE| AB[Not found]
    RR -->|needs_calc| CALC[LLM extracts cited numbers → Python AST calculator]
    RR --> GEN[Grounded JSON answer · tier from router]
    CALC --> GEN
    GEN --> V[Verify: citations retrieved? every number in a cited chunk?]
    V -->|fail| RETRY[One stricter retry → else Not found]
    V --> OUT2[Stream answer + page citations] --> TR[Cache + trace to SQLite]
```

| Layer | Choice |
|---|---|
| API | FastAPI, with SSE streaming of typed events (`step`, `token`, `citations`, `done`, `error`) |
| UI | Next.js 16 (App Router), TypeScript, Tailwind 4, shadcn/ui, lucide-react, recharts |
| LLM | LiteLLM: OpenAI, Anthropic, Gemini, Groq, Ollama; small/large tiers plus a fallback chain |
| Parsing | PyMuPDF + pymupdf4llm: per-page markdown, tables kept whole, 4 parallel workers. PDF, HTML (SEC filings), TXT/MD, EPUB |
| Embeddings, BM25, rerank | fastembed (bge-small-en-v1.5, Qdrant/bm25, ms-marco-MiniLM-L-6-v2), all local on CPU |
| Vector DB | Qdrant, embedded on disk, with named `dense` and `sparse` vectors |
| Storage | SQLite: documents, chat sessions, rolling summaries, memories, semantic cache, request traces |

## Features beyond the core pipeline

- **Grounded charts:** ask "how has X changed over the years?" and get a chart in which every value was checked against its cited page.
- **Related questions:** 3 suggested follow-ups after each answer.
- **Deep research:** a toggle that splits the question into sub-questions, reads more of the report and writes a structured answer.
- **Chat history:** saved sessions with search, rename and delete. Long chats stay fast because older turns are summarised.
- **Cross-chat memory (opt-in):** remembers your preferences across chats. View and delete memories in Settings.
- **Web search (Tavily, optional):** used automatically only when your documents can't answer, and clearly labelled.
- **SEC EDGAR import:** type a ticker and pick a form (10-K, 10-Q, 20-F, 40-F) to fetch and index the latest filing. Set `SEC_USER_AGENT` in `.env`.
- **See the real page:** citations open the actual page with the cited passage highlighted, or the extracted text.
- **Plain-English key terms:** jargon in an answer (float, GAAP, underwriting…) is explained underneath, labelled as general definitions, never as document facts.
- **Executive briefing, document scope, export:** a one-click Deep-research overview of a report, a picker for which documents a chat searches, and Markdown export of a thread.

A guided tour of how everything works, with measured numbers and interview questions, is in [docs/STUDY_GUIDE.md](docs/STUDY_GUIDE.md).

## Run locally

Requires Python 3.11+, Node 20+, and GNU make (optional; the raw commands are in the `Makefile`).

```bash
make install            # venv + pip install + npm ci
cp .env.example .env    # optional; defaults work
cp frontend/.env.local.example frontend/.env.local
make api                # http://localhost:8000  (docs at /docs); API_PORT=8001 to change
make ui                 # http://localhost:3000
make test               # backend tests (no API key needed: LLM calls are faked)
```

Then:
1. Open **Settings** and pick a provider. Paste an API key, or choose Ollama, which needs no key.
2. Click **Test connection**.
3. On **Documents**, upload a file or import from EDGAR by ticker. A 150-page report indexes in about 2 minutes on a laptop CPU, with live progress.
4. Ask questions in **Chat**.

### Deploy (free): everything on Vercel

Live at https://filinglens-analyst-companion.vercel.app. The UI and the API (cloud mode: Neon Postgres, Qdrant Cloud, Jina AI) both run on Vercel. Step-by-step: [docs/DEPLOY.md](docs/DEPLOY.md).

### Docker

```bash
docker compose up --build    # UI on :3000, API on :8000, data in a named volume
```

`Dockerfile.space` builds a single-container image for Hugging Face Spaces (port 7860). Next.js serves the UI and proxies `/api/*` to FastAPI inside the container, so the browser stays on one origin.

## Your API key

- The key is stored only in the browser tab's `sessionStorage`. It is never put in `localStorage` or cookies, and it disappears when the tab closes.
- It is sent per request as `X-LLM-Key`, used for that request only, never written to disk or logs, and masked out of any error text returned to the UI.
- CORS allows only `FRONTEND_ORIGIN`.

## Evaluation

`make eval` indexes `eval/data/report.pdf` (Berkshire Hathaway 2023 Annual Report, 152 pages) into a separate index. It then scores `eval/golden.jsonl`: 20 questions, 3 of which the report can't answer. Results go to `eval/results.md`.

Retrieval results (local models, no LLM):

| Metric | Value |
|---|---|
| Hit@5 | 0.94 |
| MRR | 0.68 |
| Hit@3 / Hit@8 | 0.76 / 1.00 |
| Abstention accuracy, retrieval gate only (threshold 0.0) | 0.95 |
| Rerank latency per question (this laptop CPU) | about 1.0 s (was 2.5 s with a pool of 20) |
| Indexing a 152-page PDF | 129 s (was about 208 s) |

How these were tuned, with before/after tables, is in [eval/TUNING.md](eval/TUNING.md).

The answer metrics need an LLM: citation precision, abstention accuracy end to end, answer accuracy, faithfulness, cost and latency. To run them:

```bash
EVAL_PROVIDER=openai EVAL_SMALL_MODEL=gpt-5-mini EVAL_LARGE_MODEL=gpt-5 EVAL_LLM_KEY=sk-... make eval
```

> The golden set was drafted from the report with page numbers checked against the PDF text. Review every pair yourself before quoting any number.

## Known limitations

- **Parser:** pymupdf4llm garbles some complex tables. The page-19 performance table loses its row labels, so "overall gain 1964–2023" isn't retrievable.
- **Retrieval gate:** a question about a missing year ("revenue in 2025") still scores high on rerank because the topic matches. Only the answer step can abstain on it. The verifier is the backstop.
- **Number verification** accepts any number that equals a cited number at some ×1000 scale after rounding, and ignores small integers (≤ 10). It catches invented figures, not every misattributed one.
- **Streaming:** the answer is streamed only after it passes verification. Pipeline steps stream live, but the first answer token arrives after generation finishes. This is deliberate: an unverified number never reaches the screen.
- **HTML filings:** MuPDF's layout of SEC HTML can clip narrow table labels (the numbers survive). Inline-XBRL facts aren't used yet.
- **Embedding is now the indexing bottleneck** (about 90 s of the 129 s on CPU).
- **Embedded Qdrant** is single-process. Run one API worker, or switch to a Qdrant server to scale out.
- **Trace storage:** traces keep the question after PII redaction, never the API key.

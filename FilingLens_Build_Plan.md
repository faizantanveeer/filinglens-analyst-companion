# FilingLens — Grounded Q&A over Company Annual Reports

**One-line pitch:** Upload a company's annual report (PDF) and ask questions in plain English. Every answer is grounded in the document, cites its page, calculates numbers in code instead of letting the LLM guess, and says "not found" instead of making things up.

**Why this project:** Finance documents are long, full of tables, and wrong numbers are costly. That makes them a natural place to show the hard parts of an AI system: retrieval quality, preventing hallucinations, routing questions between models, guardrails, cost control, and evaluation. It's a different domain from my day job.

---

## 0. Instructions for Claude Code (read first)

- Build **one phase at a time**. After each phase, stop and print: (a) files changed, (b) how to run or test that phase, (c) a short explanation of each design decision. Do not start the next phase until the developer says "next".
- Keep code **simple and explicit**. No agent frameworks and no premature abstractions. Each pipeline step is a plain Python function with a docstring explaining *why* it exists.
- Be token efficient: don't reprint unchanged files, and don't generate boilerplate tests beyond what each phase lists.
- Python 3.11+. Install the latest stable versions, then pin them in `requirements.txt`.
- Frontend: Node 20+. Pin exact versions in `frontend/package.json` (no `^` ranges). Ask before adding any dependency not listed in the stack table.
- Never log or persist API keys.

---

## 1. Tech Stack (and why)

| Layer | Choice | Why |
|---|---|---|
| Backend API | FastAPI | Async, typed with Pydantic, auto-generated docs at `/docs` |
| UI | Next.js (App Router) + TypeScript + Tailwind CSS + shadcn/ui | Real product UI: streamed chat over SSE, citation side panel, responsive layout; typed end to end |
| UI extras | lucide-react (icons), recharts (Insights charts) | Lightweight; no heavy animation libraries |
| LLM gateway | LiteLLM | One interface for OpenAI, Anthropic, Gemini, Groq and **Ollama (local, open source)**; built-in fallbacks and token/cost counting |
| PDF parsing | PyMuPDF + `pymupdf4llm` | Fast; outputs Markdown and keeps page numbers |
| Embeddings | `fastembed` (BAAI/bge-small-en-v1.5) | Open source, runs locally on CPU, **costs no API tokens** |
| Sparse / keyword | `fastembed` BM25 sparse vectors | Exact matches for terms like "EBITDA" or "FY2024" that dense embeddings miss |
| Vector DB | Qdrant (local embedded mode) | No server needed; supports dense + sparse hybrid search |
| Reranker | `fastembed` cross-encoder (ms-marco MiniLM) | Re-scores the top candidates precisely; local and free |
| Storage / logs | SQLite | Zero setup; holds document metadata, cache and request traces |
| Packaging | Docker + docker-compose | One-command run; can be deployed to Hugging Face Spaces |

**Model tiers (set in Settings, not hard-coded):**
- `small` tier: the provider's cheapest fast model, used for routing, query rewriting and judging.
- `large` tier: the provider's stronger model, used for complex answers.
- Fallback chain: user's primary provider, then the secondary provider if configured, then local Ollama if running.

---

## 2. Project Structure

```
filinglens/
├── backend/app/
│   ├── main.py              # FastAPI routes
│   ├── config.py            # defaults: chunk size, top_k, thresholds
│   ├── schemas.py           # Pydantic request/response models
│   ├── llm/gateway.py       # LiteLLM wrapper: tiers, fallbacks, JSON mode, token/cost capture
│   ├── ingest/
│   │   ├── parser.py        # PDF → markdown pages
│   │   ├── chunker.py       # structure-aware chunks with metadata
│   │   └── indexer.py       # dense + sparse embeddings → Qdrant
│   ├── retrieval/
│   │   ├── hybrid.py        # dense + BM25, fused with RRF
│   │   └── rerank.py        # cross-encoder rerank + score threshold
│   ├── pipeline/
│   │   ├── guard_input.py   # length, injection, PII checks
│   │   ├── rewrite.py       # follow-up → standalone query
│   │   ├── router.py        # intent + complexity → model tier
│   │   ├── answer.py        # grounded generation, JSON output
│   │   ├── calculator.py    # safe arithmetic (AST-based, no eval)
│   │   ├── verify.py        # citation + number grounding checks
│   │   └── orchestrator.py  # runs the steps, records a trace
│   ├── cache/semantic_cache.py
│   └── obs/tracer.py        # per-request trace → SQLite
├── frontend/                # Next.js (App Router, TypeScript)
│   ├── app/
│   │   ├── layout.tsx       # shell: collapsible sidebar, theme toggle, toaster
│   │   ├── page.tsx         # / → Chat
│   │   ├── documents/page.tsx
│   │   ├── settings/page.tsx
│   │   └── insights/page.tsx
│   ├── components/          # app components + components/ui (shadcn)
│   ├── lib/
│   │   ├── api.ts           # the one typed API client (base URL from NEXT_PUBLIC_API_URL)
│   │   ├── sse.ts           # typed SSE parser: step | token | citations | done | error
│   │   └── settings.ts      # session-only settings + API key (sessionStorage)
│   └── package.json         # exact pinned versions
├── eval/
│   ├── golden.jsonl         # 15–20 hand-written Q&A (incl. 3 unanswerable)
│   ├── run_eval.py
│   └── results.md           # generated
├── tests/                   # small, focused tests per phase
├── docker-compose.yml  Dockerfile.backend  Dockerfile.frontend
├── .env.example  Makefile  README.md
```

---

## 3. Request Flow

```mermaid
flowchart TD
    Q[User question] --> G1[Input guardrails]
    G1 -->|blocked| R0[Safe refusal]
    G1 --> RW[Rewrite follow-up to standalone query - small model, skipped on first turn]
    RW --> C{Semantic cache hit?}
    C -->|yes| OUT[Return cached answer]
    C -->|no| RT[Router - small model, JSON]
    RT -->|out_of_scope| R1[Polite scope message]
    RT --> RET[Hybrid retrieval: dense + BM25 → RRF]
    RET --> RR[Cross-encoder rerank]
    RR -->|top score < threshold| AB[Abstain: not found in documents]
    RR --> GEN[Grounded answer - tier chosen by router]
    GEN -->|needs_calc| CALC[Extract cited numbers → Python calculator]
    CALC --> GEN
    GEN --> V[Verify citations + numbers]
    V -->|fail| RETRY[One retry with stricter prompt → else abstain]
    V --> OUT2[Answer + page citations]
    OUT2 --> CACHE[Store in cache] --> TR[Trace: tokens, cost, latency per step]
```

---

## 4. Build Phases

Each phase lists **Must** items (needed for the demo) and **Done when** criteria. Phases 1–5 and 7 are the minimum version to have ready. Phases 6 and 8 are nice to have.

### Phase 0 — Setup (~20 min)
- Repo skeleton, virtual environment, `requirements.txt`, `Makefile` (`make api`, `make ui`, `make eval`), `.env.example`.
- Next.js skeleton: routes `/` (Chat), `/documents`, `/settings`, `/insights`; collapsible sidebar; light/dark toggle; responsive to mobile; `lib/api.ts` with a typed `health()` call.
- Backend CORS allows only the frontend origin (`FRONTEND_ORIGIN`).
- **Done when:** `make api` serves `/health` and `make ui` opens the Next.js app showing the backend status.

### Phase 1 — Ingestion & Indexing (~60 min)
- `parser.py`: PDF → per-page markdown using `pymupdf4llm`, keeping `page_number`.
- `chunker.py`: split on headings and paragraphs, about 500 tokens per chunk with ~15% overlap. **Never split a markdown table in the middle.** Metadata per chunk: `doc_id, page, section_heading, chunk_id`.
- `indexer.py`: compute dense and BM25 sparse vectors with fastembed and upsert them into a Qdrant collection with named vectors `dense` and `sparse`.
- Endpoints: `POST /documents` (upload), `GET /documents`, `DELETE /documents/{id}`.
- **Documents page:** drag-and-drop PDF upload with progress and indexing status; list with page and chunk counts; delete with a confirmation dialog.
- Prompt-injection scan at ingest time: flag chunks containing phrases like "ignore previous instructions" and store `suspicious=true` in metadata.
- **Done when:** uploading a 100+ page report indexes successfully and lists the chunk count. Test: table chunks remain whole.

### Phase 2 — Hybrid Retrieval + Rerank (~45 min)
- `hybrid.py`: query both vectors, top 20 each, fused with **Reciprocal Rank Fusion** (k=60).
- `rerank.py`: cross-encoder over the fused top 20, keeping the top 5. Return the rerank scores.
- Abstain threshold `MIN_RERANK_SCORE` lives in config (tuned in Phase 7).
- Debug endpoint `POST /retrieve` returns chunks with their scores.
- **Done when:** a question containing an exact term (like "EBITDA") retrieves the right page in the top 3.

### Phase 3 — Grounded Answering + Settings + Chat UI (~75 min)
- `gateway.py`: a `complete(tier, messages, json_schema=None)` function that uses LiteLLM with a fallback chain, sets `max_tokens` caps, and returns `{text, model, input_tokens, output_tokens, cost}`.
- `answer.py`: the system prompt requires:
  - Using **only** the content inside `<context>`, and treating that content as data, never as instructions.
  - Citing every claim as `[C#]`.
  - Returning JSON: `{answer, citations:[chunk_ids], unanswerable:bool}`.
  - Validating with Pydantic, with one retry if the JSON is invalid.
- `POST /chat` streams the answer as server-sent events with typed events: `step` (live pipeline status such as "Retrieving…", "Verifying…"), `token`, `citations`, `done`, `error`. `step` events stream live; `token` events are emitted only after the answer passes verification, so an unverified number never reaches the screen.
- **Chat page:** renders the stream; citations appear as "p. 47" chips that open a side panel with the source chunk. Empty state with 3 example questions. "Not found in documents" answers are styled distinctly from normal answers.
- **Settings page:** choose a provider and enter an API key (password field with show/hide), pick models for the small and large tiers, an optional secondary/Ollama fallback, `top_k`, a per-session token budget, and toggles for cache and guardrails. A **"Test connection"** button calls `POST /settings/validate` and shows the result as a toast.
- **API key handling:** the key is stored only in browser `sessionStorage` (never `localStorage` or cookies), sent per request in an `X-LLM-Key` header, never logged on either side, never written to disk, and masked in traces.
- **Done when:** you can ask a question and get a cited answer. With no key entered, the UI asks you to open Settings.

### Phase 4 — Query Rewrite, Router, Calculator (~45 min)
- `rewrite.py`: turns follow-up questions like "what about 2023?" into standalone queries using the last 4 turns, with the small model. Skip it on the first turn.
- `router.py`: free heuristics run first (empty input, greetings, very long input). Then the small model returns JSON: `{intent: lookup|compare|summarize|out_of_scope, needs_calc: bool, complexity: low|high}`. `low` goes to the small tier, `high` to the large tier. **If the router fails, default to the large tier**, so a failure costs extra tokens rather than answer quality.
- `calculator.py`: when `needs_calc` is true, the LLM extracts `{label, value, unit, chunk_id}` for each number it needs. Python then computes the growth, ratio or difference using a safe AST evaluator, and the LLM writes the final sentence. **The LLM never does the arithmetic.**
- **Done when:** "How much did revenue grow from 2023 to 2024 in percent?" returns the correct figure and cites both source pages.

### Phase 5 — Guardrails & Verification (~45 min)
- `guard_input.py`: a maximum question length; injection patterns (attempts to reveal the system prompt or override instructions); PII regex (emails, phone numbers, card-like numbers) that is redacted before anything is sent to the LLM.
- `verify.py`, which needs no LLM calls:
  1. Every cited `chunk_id` must be in the retrieved set.
  2. Every number in the answer must appear in a cited chunk or be a calculator output.
  3. If a check fails, retry once with a stricter prompt. If it fails again, abstain.
- Optional: for `complexity: high` questions only, the small model acts as a judge and rates faithfulness (yes/no plus a reason).
- **Done when:** the three unanswerable test questions return "not found in the provided documents", and an injection attempt gets a refusal.

### Phase 6 — Cache & Observability (~40 min) *(nice to have)*
- `semantic_cache.py`: the key is the hash of the document set plus the embedding of the *standalone* query (on follow-ups the cache is checked after the rewrite, since "what about 2023?" alone is ambiguous). A cosine similarity ≥ 0.95 counts as a hit. The cache is invalidated whenever documents change.
- `tracer.py`: one SQLite row per request: route, model, tokens in/out, cost, latency per step, chunk ids, cache hit, verification result.
- **Insights page** (`/insights`, charts with recharts): total cost, average tokens per query, cache hit rate, p50/p95 latency, and the distribution of routes. Backed by `GET /insights`.
- **Done when:** asking a repeated question returns instantly with 0 tokens shown in the trace.

### Phase 7 — Evaluation (~40 min)
- `golden.jsonl`: 15–20 questions written **by hand** from one real annual report: `{question, expected_pages, expected_answer_contains, answerable}`, including 3 that the report can't answer.
- `run_eval.py` writes `results.md` with: **Hit@5, MRR** (retrieval quality), **citation precision**, **abstention accuracy**, faithfulness rate (if the judge is enabled), average cost per query, and p50 latency.
- Use it to tune `MIN_RERANK_SCORE` and `top_k`. Record the before and after numbers.
- **Done when:** `make eval` produces `results.md`. **These are the only numbers to quote in an interview.**

### Phase 8 — Package & Deploy (~30 min) *(nice to have)*
- Docker images for the backend (Python) and frontend (Next.js `output: "standalone"`, Node runtime); `docker compose up` runs everything. `NEXT_PUBLIC_API_URL` is a build arg; backend `FRONTEND_ORIGIN` must match the deployed frontend origin.
- Deploy to Hugging Face Spaces (Docker). Since a Space exposes one port, serve both behind one container (Next.js proxies `/api` to FastAPI via `rewrites`), or deploy the frontend separately (e.g. Vercel). Users bring their own key through Settings.
- README: problem, architecture diagram, how to run, eval results table, known limitations.

### Additions after Phase 8
- **Charts:** trend-style questions ("over the years", "plot", "by segment") get a chart. The LLM proposes points; Python keeps only values found in the chunk each one cites (`pipeline/chart.py`). Presentation words are stripped from the retrieval query, since "plot …" lowered rerank scores by ~2.
- **Follow-up suggestions:** the answer JSON carries 3 `follow_ups`, so suggestions cost no extra call.
- **Deep research toggle:** decomposes the question into ≤4 sub-questions, retrieves for each, merges ≤10 chunks, uses the large tier and returns a structured answer (`pipeline/deep.py`). Default answers are also richer (2–6 sentences).
- **Web search fallback (Tavily):** runs only when the documents can't answer (out of scope, below the abstain threshold, unanswerable, or failed verification). The key is session-only (`X-Search-Key`); web text is treated as untrusted data and verified the same way; answers are labelled "From the web".
- **Azure OpenAI provider** (endpoint restricted to Azure domains).
- **UI:** the sidebar closes fully (Ctrl/⌘+B); the composer stays pinned and auto-scroll follows to the true bottom; charts use a proportional year axis, a validated palette, a legend and a table view; mobile request list on Insights.

### Chat sessions, context management and memory
- **Sessions** (`backend/app/sessions.py`, SQLite): every chat is a server-side session with saved turns (answer, citations, chart, suggestions, metadata). Sidebar history grouped by date, with search over titles and message text, rename and delete (cascades to messages). URL `/c/<id>`. Sessions were first scoped to an anonymous per-browser `X-Client-Id`; accounts (below) replaced that.
- **Context management:** conversation history only feeds the small-model rewrite step. The grounded answer sees the standalone question plus chunks. The last 4 turns go in verbatim (each trimmed to 600 chars); older turns are folded into a ≤150-word rolling summary in batches of 2, in a background task after the answer streams. Prompt size stays bounded regardless of chat length.
- **Cross-chat memory** (`backend/app/memory.py`, opt-in, off by default): the small model extracts durable user facts and preferences from questions (never document facts). Memories are stored with local embeddings, de-duplicated (cosine ≥ 0.9), capped at 50, injection-checked and PII-redacted. The top 3 relevant (cosine ≥ 0.5) go into the answer prompt as style-only preferences; verification still rejects unsupported numbers. Personalised answers bypass the shared semantic cache. Memories are managed (list, delete, clear) in Settings and never mix into another session's history.

### Final pass: speed, documents, domain help
- **Faster queries:** rerank pool 20 → 10, measured: 2.5 s → 1.0 s per question and Hit@5 0.88 → 0.94. Models are warmed at API start-up, and the query embedding is cached and reused by cache, retrieval and memory. See `eval/TUNING.md`.
- **Faster ingestion:** page-parallel parsing (4 processes) overlapped batch by batch with embedding and indexing: 208 s → 129 s for the 152-page report. Live progress (stage and percentage) is shown on the Documents page.
- **More document types, no new dependency:** PDF, HTML/HTM (SEC filings), TXT/MD and EPUB through MuPDF, with content sniffing on upload.
- **Page preview:** the source panel renders the real page with the cited passage highlighted. Non-PDF documents are converted to PDF once; renders are cached on disk.
- **Plain-English key terms:** an optional `key_terms` field in the answer JSON, rendered as "General definitions, not from your documents". Any definition containing a digit is dropped server-side, so figures only ever come from cited sources.
- **Workflow:** "Executive briefing" Deep-research starter, per-chat document scope picker, Markdown export of a thread.

### Deployment: cloud mode on Vercel
- `DEPLOY_MODE=cloud` swaps local services for hosted ones: Postgres (Neon) for SQLite, Qdrant Cloud for embedded Qdrant, Jina for fastembed, and a slim OpenAI-compatible client for LiteLLM. Files are stored in Postgres in 4 MB pieces and indexed inside the request (≤ 300 s). See `docs/DEPLOY.md`.

### Accounts, credits and RBAC
- Email + password accounts (scrypt), opaque bearer tokens stored as SHA-256, roles guest / user / admin (`ADMIN_EMAILS`).
- Every visitor starts as a guest: 5 questions and 1 document. Sign-up upgrades the guest in place; logging in merges guest data. Accounts get 200 questions a month and 20 documents.
- All documents, chats, memories and traces are owner-scoped; other users' ids return 404. Credits are charged atomically and refunded on failure; 402 opens the sign-up dialog.
- Rate limits on guest creation and log-in; CSP and security headers on the UI and API.

### UI refinements
- Collapsed sidebar shows an icon rail. A profile icon menu (email, Settings, Log out) replaces the email in the sidebar.
- Each chat has a ⋯ menu (Pin/Unpin, Rename, Delete); pinned chats have their own section.
- Usage alerts: toasts when session tokens or estimated spend pass thresholds set in Settings, and at 80% of the token budget. Cloud mode estimates cost from a list-price table.
- Log-out clears the API keys from the tab; signing up or logging in from a guest keeps them.
- The SEC EDGAR import was removed; documents come from uploads only. The header shows API status only when the API is unreachable.

---

## 5. Key Design Decisions (be ready to defend each)

1. **Hybrid search over dense-only:** financial terms and exact years need keyword matching. RRF fuses the two rankings without having to calibrate their scores against each other.
2. **Rerank before generation:** a cross-encoder reads the query and chunk together, so it's more accurate but slower. That's why it runs only on the top 20 candidates.
3. **Abstain threshold:** saying "I don't know" beats a confident wrong answer, especially in finance. The threshold is tuned on the eval set, not guessed.
4. **Calculation in code:** LLMs are unreliable at arithmetic, while Python is deterministic. Calculator results are also easy to verify.
5. **Verification without an LLM:** citation and number checks are free, fast and deterministic. The LLM judge is used only where it's worth its cost.
6. **Router fails toward quality:** if the classifier breaks, the system spends more tokens rather than risking a worse answer.
7. **Local embeddings and rerank:** no API cost and no data sent out for indexing. Only the final generation uses the user's key.
8. **No agent framework:** the pipeline is linear with one loop (retry), and plain functions are easier to debug, test and explain. A framework would be worth it with real branching tool use.
9. **Bring your own key:** keys live only in the browser tab's `sessionStorage` and travel per request. The deployed demo costs me nothing, and users stay in control of their own data and spending.

---

## 6. Understanding Checkpoints

After each phase, answer these **out loud, without looking at the code**. If you can't, ask Claude Code to explain that part before moving on.

- **P1:** Why ~500 tokens with overlap? What breaks if a table is split? What does the `sparse` vector capture that `dense` doesn't?
- **P2:** How does RRF work, and why k=60? Why rerank 20 candidates and keep 5? What happens if no chunk passes the threshold?
- **P3:** How does the prompt stop the model using outside knowledge? What happens when the JSON is invalid? Trace exactly where the API key travels.
- **P4:** Why rewrite before retrieving, not after? Why does a router failure default to the large tier? Walk through a percentage-growth question end to end.
- **P5:** Give two concrete injection examples and show where each gets blocked. Why check numbers with code rather than an LLM?
- **P6:** Why 0.95 similarity, and what goes wrong at 0.85? When does the cache become invalid?
- **P7:** What do Hit@5 and MRR each measure? Why include unanswerable questions? Which number improved after tuning, and why?

---

## 7. Likely Interview Questions (prepare your own answers)

- Walk me through the architecture. Why each component?
- How do you prevent hallucinations? How do you know it works?
- How did you evaluate retrieval and answer quality? What were the numbers?
- What fails in your system today? What would you improve next?
- How would you scale this to 10,000 documents or 1,000 users?
- How do you control cost per query?
- How do you handle prompt injection from uploaded documents?
- Why didn't you use LangChain or LangGraph here?

**Honest framing:** present this as *a personal project I built recently to go deep on grounded RAG for financial documents*. Quote only the numbers from `eval/results.md`. Don't claim it has users or runs in production.

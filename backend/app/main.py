"""FastAPI entry point. Routes stay thin; pipeline logic lives in plain functions elsewhere."""

import json
import logging
import re
import threading
import uuid

from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from . import documents
from . import memory as user_memory
from . import sessions
from .config import settings
from .embeddings import warm_up
from .ingest import edgar
from .ingest.parser import SUPPORTED, filetype_for
from .ingest.preview import render_page
from .llm.gateway import LLMConfig, LLMError, complete
from .obs.tracer import insights as trace_insights
from .pipeline import orchestrator
from .pipeline.web_search import WebSearchError, tavily_search
from .retrieval.hybrid import hybrid_search
from .retrieval.rerank import passes_threshold, rerank
from .schemas import (
    ChatRequest,
    DocumentOut,
    EdgarImportRequest,
    LLMSettings,
    RenameRequest,
    RetrieveRequest,
    UploadComplete,
    UploadStart,
    ValidateRequest,
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Warm the local models in the background: the API is reachable immediately, and the first
    # question no longer pays for model loading.
    threading.Thread(target=warm_up, daemon=True).start()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Only the frontend origin may call the API from a browser. No cookies are used,
# so credentials stay off. The key headers must be allowed explicitly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.frontend_origin_regex or None,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-LLM-Key", "X-LLM-Fallback-Key", "X-Search-Key", "X-Client-Id"],
)


def llm_config(s: LLMSettings, key: str | None, fallback_key: str | None) -> LLMConfig:
    """Build the per-request LLM config. The key is used for this request only, never stored or logged."""
    if s.provider != "ollama" and not key:
        raise HTTPException(401, "Missing API key. Add one in Settings.")
    if s.provider == "azure" and not s.azure_endpoint:
        raise HTTPException(422, "Azure OpenAI needs an endpoint. Add it in Settings.")
    return LLMConfig(
        s.provider,
        s.small_model,
        s.large_model,
        key,
        s.fallback_model or None,
        fallback_key,
        azure_endpoint=s.azure_endpoint,
        azure_api_version=s.azure_api_version,
    )


log = logging.getLogger(__name__)
CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def owner_of(x_client_id: str | None, required: bool = True) -> str | None:
    """Sessions and memories belong to an anonymous per-browser id (no login in this app).

    Why: without it, everyone using a shared deployment would see each other's chats.
    It's not authentication. Anyone holding the id can read its sessions, so it's only
    as private as the browser that generated it.
    """
    if x_client_id and CLIENT_ID.match(x_client_id):
        return x_client_id
    if required:
        raise HTTPException(400, "Missing or invalid X-Client-Id header.")
    return None


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check used by the UI status badge and Docker healthchecks."""
    return {"status": "ok"}


# ---------- Documents ----------


def _looks_like(filetype: str, data: bytes) -> bool:
    """Cheap content check so a renamed binary can't masquerade as a supported type."""
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if filetype == "pdf":
        return data.startswith(b"%PDF")
    if filetype == "epub":
        return data.startswith(b"PK")
    if filetype == "html":
        return head.startswith(b"<") and (b"<html" in data[:20000].lower() or b"<!doctype" in head or b"<?xml" in head)
    try:  # txt / md must be text
        data[:20000].decode("utf-8")
        return b"\x00" not in data[:20000]
    except UnicodeDecodeError:
        return False


def _run_ingest(background: BackgroundTasks, doc_id: str) -> dict:
    """Local: index in the background (the UI polls progress). Serverless: index inside this request,
    since work after the response may be frozen. It fits Vercel's 300 s limit for ~150-page reports."""
    if settings.serverless:
        documents.ingest(doc_id)
    else:
        background.add_task(documents.ingest, doc_id)
    return documents.get(doc_id)


def _store_and_index(background: BackgroundTasks, data: bytes, filename: str, filetype: str, source_url: str | None = None) -> dict:
    digest = documents.sha256(data)
    if existing := documents.find_by_hash(digest):
        return existing  # same file already uploaded: don't index it twice
    doc_id = uuid.uuid4().hex[:12]
    doc = documents.register(doc_id, filename[:200], digest, filetype, source_url)
    documents.save_file(doc_id, filetype, data)
    return _run_ingest(background, doc_id) or doc


# Chunked uploads: the browser sends files in <= 4 MB pieces, so uploads work on serverless hosts
# with small request-body limits (Vercel: 4.5 MB). Local mode uses the same flow.


@app.post("/uploads", status_code=201)
def start_upload(body: UploadStart):
    ftype = filetype_for(body.filename)
    if not ftype:
        raise HTTPException(415, f"Unsupported file type. Use one of: {', '.join(sorted(SUPPORTED))}.")
    if body.size > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")
    upload_id = "up" + uuid.uuid4().hex[:10]
    documents.drop_pieces(upload_id)
    return {"upload_id": upload_id, "chunk_size": documents.PIECE, "filetype": ftype}


@app.put("/uploads/{upload_id}/{seq}", status_code=204)
async def upload_piece(upload_id: str, seq: int, request: Request):
    if not re.fullmatch(r"up[0-9a-f]{10}", upload_id) or not 0 <= seq < 64:
        raise HTTPException(400, "Bad upload id or piece number.")
    data = await request.body()
    if not data or len(data) > documents.PIECE:
        raise HTTPException(413, "Each piece must be between 1 byte and 4 MB.")
    documents.add_piece(upload_id, seq, data)


@app.post("/uploads/{upload_id}/complete", response_model=DocumentOut, status_code=202)
def complete_upload(upload_id: str, body: UploadComplete, background: BackgroundTasks):
    if not re.fullmatch(r"up[0-9a-f]{10}", upload_id):
        raise HTTPException(400, "Bad upload id.")
    data = documents.read_pieces(upload_id)
    documents.drop_pieces(upload_id)
    ftype = filetype_for(body.filename)
    if not data:
        raise HTTPException(400, "No data received.")
    if not ftype or not _looks_like(ftype, data):
        raise HTTPException(415, f"The file content doesn't look like {(ftype or 'a supported type').upper()}.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")
    return _store_and_index(background, data, body.filename, ftype)


@app.post("/documents", response_model=DocumentOut, status_code=202)
async def upload_document(background: BackgroundTasks, file: UploadFile = File(...)):
    """Accept a PDF, HTML (e.g. an EDGAR filing), TXT/MD or EPUB, then index it in the background.
    The UI polls GET /documents for live progress."""
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")
    name = file.filename or "document.pdf"
    ftype = filetype_for(name)
    if not ftype:
        raise HTTPException(415, f"Unsupported file type. Use one of: {', '.join(sorted(SUPPORTED))}.")
    if not _looks_like(ftype, data):
        raise HTTPException(415, f"The file content doesn't look like {ftype.upper()}.")
    return _store_and_index(background, data, name, ftype)


@app.post("/documents/edgar", response_model=DocumentOut, status_code=202)
def import_from_edgar(body: EdgarImportRequest, background: BackgroundTasks):
    """Fetch the latest filing of a form type for a ticker from SEC EDGAR and index it."""
    try:
        filing = edgar.latest_filing(body.ticker, body.form)
    except edgar.EdgarError as exc:
        raise HTTPException(502, str(exc)) from None
    return _store_and_index(background, filing["content"], filing["filename"], "html", filing["url"])


@app.get("/documents/{doc_id}/pages/{page}.png")
def page_image(doc_id: str, page: int, highlight: str = Query(default="", max_length=4000)):
    """Rendered page with the cited passage highlighted. Rendered once, then served from disk."""
    if not documents.get(doc_id):
        raise HTTPException(404, "Document not found.")
    try:
        png = render_page(doc_id, page, highlight)
    except ValueError:
        raise HTTPException(404, "Page not found.") from None
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/documents", response_model=list[DocumentOut])
def list_documents():
    return documents.list_all()


@app.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str):
    doc = documents.get(doc_id)
    if doc and doc.get("protected"):
        raise HTTPException(403, "The sample document can't be deleted.")
    if not documents.delete(doc_id):
        raise HTTPException(404, "Document not found.")


# ---------- Retrieval (debug) ----------


@app.post("/retrieve")
def retrieve(req: RetrieveRequest):
    """Debug view of retrieval: fused candidates reranked, with every score."""
    ranked = rerank(req.query, hybrid_search(req.query, req.doc_ids), req.top_k)
    return {
        "passes_threshold": passes_threshold(ranked),
        "min_rerank_score": settings.min_rerank_score,
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "page": c.page,
                "section": c.section_heading,
                "ranks": c.ranks,
                "rrf_score": round(c.rrf_score, 5),
                "rerank_score": round(c.rerank_score or 0.0, 4),
                "text": c.text,
            }
            for c in ranked
        ],
    }


# ---------- Chat ----------


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/chat")
def chat(
    req: ChatRequest,
    x_llm_key: str | None = Header(default=None),
    x_llm_fallback_key: str | None = Header(default=None),
    x_search_key: str | None = Header(default=None),
    x_client_id: str | None = Header(default=None),
):
    """Stream typed events: step, token, chart, citations, suggestions, done, error (server-sent events).

    With a session_id, history comes from the database (bounded by the rolling summary), and the
    completed turn is saved. Summary folding and memory extraction run after the stream ends.
    """
    cfg = llm_config(req.settings, x_llm_key, x_llm_fallback_key)
    owner = owner_of(x_client_id, required=bool(req.session_id) or req.settings.use_memory)
    if req.session_id and not sessions.get(owner, req.session_id):
        raise HTTPException(404, "Chat session not found.")
    convo = sessions.conversation(owner, req.session_id) if owner else None

    def stream():
        tokens, payload, steps, done = [], {}, [], None
        for event, data in orchestrator.run(req, cfg, x_search_key, convo):
            if event == "token":
                tokens.append(data["text"])
            elif event == "step":
                steps.append(data["label"])
            elif event in ("chart", "citations", "suggestions"):
                payload[event] = data[event]
            elif event == "done":
                done = data
            yield sse(event, data)
        if done and owner and req.session_id:
            payload.update(answer_type=done["answer_type"], meta=done, steps=steps, deep=req.deep)
            sessions.record_turn(owner, req.session_id, req.question.strip(), "".join(tokens), payload)
            if settings.serverless:
                after_turn(owner, req, cfg)  # the client already has "done"; finish before the function ends
            else:
                threading.Thread(target=after_turn, args=(owner, req, cfg), daemon=True).start()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def after_turn(owner: str, req: ChatRequest, cfg: LLMConfig) -> None:
    """Background work that must not delay the answer: fold old turns into the session summary,
    and (only if the user opted in) extract cross-chat memories from the question."""
    try:
        if req.session_id:
            sessions.maybe_fold(owner, req.session_id, cfg)
        if req.settings.use_memory:
            user_memory.extract_and_store(owner, req.session_id, req.question, cfg)
    except Exception as exc:
        log.warning("after_turn failed: %s", type(exc).__name__)


# ---------- Sessions ----------


@app.get("/sessions")
def list_sessions(q: str = "", x_client_id: str | None = Header(default=None)):
    return sessions.list_sessions(owner_of(x_client_id), q[:200])


@app.post("/sessions", status_code=201)
def create_session(x_client_id: str | None = Header(default=None)):
    return sessions.create(owner_of(x_client_id))


@app.get("/sessions/{sid}")
def get_session(sid: str, x_client_id: str | None = Header(default=None)):
    owner = owner_of(x_client_id)
    meta, msgs = sessions.get(owner, sid), sessions.messages(owner, sid)
    if meta is None or msgs is None:
        raise HTTPException(404, "Chat session not found.")
    return {**meta, "messages": msgs}


@app.patch("/sessions/{sid}")
def rename_session(sid: str, body: RenameRequest, x_client_id: str | None = Header(default=None)):
    if not sessions.rename(owner_of(x_client_id), sid, body.title):
        raise HTTPException(404, "Chat session not found.")
    return {"ok": True}


@app.delete("/sessions/{sid}", status_code=204)
def delete_session(sid: str, x_client_id: str | None = Header(default=None)):
    if not sessions.delete(owner_of(x_client_id), sid):
        raise HTTPException(404, "Chat session not found.")


@app.delete("/sessions")
def delete_all_sessions(x_client_id: str | None = Header(default=None)):
    return {"deleted": sessions.delete_all(owner_of(x_client_id))}


# ---------- Cross-chat memory ----------


@app.get("/memories")
def list_memories(x_client_id: str | None = Header(default=None)):
    return user_memory.list_memories(owner_of(x_client_id))


@app.delete("/memories/{mid}", status_code=204)
def delete_memory(mid: int, x_client_id: str | None = Header(default=None)):
    if not user_memory.delete(owner_of(x_client_id), mid):
        raise HTTPException(404, "Memory not found.")


@app.delete("/memories")
def clear_memories(x_client_id: str | None = Header(default=None)):
    return {"deleted": user_memory.clear(owner_of(x_client_id))}


# ---------- Settings & insights ----------


@app.post("/settings/validate")
def validate_settings(
    req: ValidateRequest,
    x_llm_key: str | None = Header(default=None),
    x_llm_fallback_key: str | None = Header(default=None),
):
    """Tiny call to the small-tier model so the user learns now, not mid-question, if the key works."""
    cfg = llm_config(req.settings, x_llm_key, x_llm_fallback_key)
    try:
        result = complete("small", [{"role": "user", "content": "Reply with the word OK."}], cfg, max_tokens=5)
    except LLMError as exc:
        return {"ok": False, "message": str(exc)[:400]}
    return {"ok": True, "model": result.model, "message": f"Connected to {result.model}."}


@app.post("/settings/validate-search")
def validate_search(x_search_key: str | None = Header(default=None)):
    """One-result Tavily search so the user learns now whether the web-search key works."""
    if not x_search_key:
        raise HTTPException(401, "Missing web search key. Add one in Settings.")
    try:
        results = tavily_search("FilingLens connection test", x_search_key, max_results=1)
    except WebSearchError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": f"Web search connected ({len(results)} result)."}


@app.get("/insights")
def insights(x_client_id: str | None = Header(default=None)):
    """Only this browser's requests: on a shared deployment, visitors must not see each other's questions."""
    return trace_insights(owner=owner_of(x_client_id, required=False) or "-")

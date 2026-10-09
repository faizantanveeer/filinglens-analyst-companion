"""Runs the pipeline step by step, yielding typed events for the SSE stream and recording a trace."""

import re
from collections.abc import Iterator
from urllib.parse import urlsplit

from .. import documents
from .. import memory as user_memory
from ..cache import semantic_cache
from ..embeddings import embed_query
from ..llm.gateway import LLMConfig, LLMError, mask
from ..obs.tracer import Trace
from ..retrieval.hybrid import Candidate, hybrid_search
from ..retrieval.rerank import passes_threshold, rerank
from ..schemas import ChatRequest
from ..sessions import Conversation
from . import deep as deep_research
from .answer import NOT_FOUND, build_context, generate_answer
from .calculator import calculate
from .chart import build_chart
from .guard_input import check_input
from .rewrite import rewrite_query
from .router import Route, retrieval_query, route
from .verify import CITATION, judge, verify_answer
from .web_search import WebSearchError, build_web_context, tavily_search

Event = tuple[str, dict]

SCOPE_MESSAGE = "I can only answer questions about the uploaded annual reports."
GREETING_MESSAGE = "Hi! Ask me anything about your uploaded annual reports."
NOT_FOUND_ANYWHERE = "Not found in your documents or on the web."


def step(sid: str, label: str) -> Event:
    return "step", {"id": sid, "label": label}


def stream_text(text: str) -> Iterator[Event]:
    """Emit the final, already-verified answer as token events (a few characters at a time)."""
    for piece in re.findall(r"\S+\s*|\s+", text):
        yield "token", {"text": piece}


def finish(
    trace: Trace,
    answer_type: str,
    text: str,
    citations: list[dict],
    extra: dict | None = None,
    follow_ups: list[str] | None = None,
    chart: dict | None = None,
) -> Iterator[Event]:
    trace.route = trace.route or answer_type
    yield from stream_text(text)
    if chart:
        yield "chart", {"chart": chart}
    yield "citations", {"citations": citations}
    if follow_ups:
        yield "suggestions", {"suggestions": follow_ups}
    trace.save()
    yield "done", {
        "answer_type": answer_type,
        "usage": trace.usage(),
        "cached": trace.cache_hit,
        "trace_id": trace.id,
        "model": trace.model,
        "route": {"intent": trace.intent, "complexity": trace.complexity},
        "verification": trace.verification,
        "latency_ms": trace.latency_ms,
        **(extra or {}),
    }


def doc_citation(label: str, c: Candidate, filenames: dict[str, str]) -> dict:
    return {
        "kind": "document",
        "label": label,
        "chunk_id": c.chunk_id,
        "doc_id": c.doc_id,
        "filename": filenames.get(c.doc_id, ""),
        "page": c.page,
        "section": c.section_heading,
        "text": c.text,
        "score": round(c.rerank_score or 0.0, 3),
        "suspicious": c.suspicious,
    }


def chart_for_client(chart: dict, labelled: dict[str, Candidate]) -> dict:
    """Swap internal chunk labels for page numbers the reader can check."""
    out = {**chart, "series": []}
    for s in chart["series"]:
        out["series"].append(
            {"name": s["name"], "points": [{"x": p["x"], "y": p["y"], "label": p["chunk"], "page": labelled[p["chunk"]].page} for p in s["points"]]}
        )
    return out


def answer_from_web(
    query: str,
    tier: str,
    cfg: LLMConfig,
    search_key: str,
    deep: bool,
    trace: Trace,
    reason: str,
    prefs: list[str] | None = None,
    explain: bool = False,
) -> Iterator[Event]:
    """Fallback when the documents can't answer: search, then the same grounded-answer + verify loop
    over web results. Clearly labelled as web content in the UI."""
    yield step("web", "Searching the web…")
    try:
        with trace.step("web_search"):
            results = tavily_search(query, search_key, max_results=8 if deep else None)
    except WebSearchError as exc:
        trace.route = "not_found"
        yield from finish(trace, "not_found", NOT_FOUND, [], {"web_error": mask(str(exc), [search_key])})
        return
    if not results:
        trace.route = "not_found"
        yield from finish(trace, "not_found", NOT_FOUND_ANYWHERE, [])
        return

    context, labelled = build_web_context(results)
    texts = {label: r["content"] for label, r in labelled.items()}
    answer, problems = None, None
    for attempt in range(2):
        yield step("answer", "Writing answer from web sources…" if attempt == 0 else "Retrying with stricter rules…")
        with trace.step("answer"):
            answer, calls = generate_answer(
                query, context, tier, cfg, None, problems, kind="web", deep=deep, preferences=prefs, explain_terms=explain
            )
        trace.add(*calls)
        trace.model = calls[-1].model if calls else trace.model
        if answer.unanswerable:
            break
        yield step("verify", "Verifying…")
        cited = list(dict.fromkeys(answer.citations + CITATION.findall(answer.answer)))
        with trace.step("verify"):
            v = verify_answer(answer.answer, cited, texts, question=query)
        if v.ok:
            trace.verification = "pass" if attempt == 0 else "retry_pass"
            break
        problems, trace.verification = v.problems, "fail"

    if answer is None or answer.unanswerable or trace.verification == "fail":
        trace.route = "not_found"
        yield from finish(trace, "not_found", NOT_FOUND_ANYWHERE, [])
        return

    cited = list(dict.fromkeys(answer.citations + CITATION.findall(answer.answer)))
    citations = [
        {
            "kind": "web",
            "label": label,
            "url": labelled[label]["url"],
            "title": labelled[label]["title"],
            "site": urlsplit(labelled[label]["url"]).hostname or "",
            "text": labelled[label]["content"],
            "suspicious": labelled[label]["suspicious"],
        }
        for label in cited
        if label in labelled
    ]
    trace.route = "web"
    extra = {"query": query, "web_reason": reason, "deep": deep}
    if prefs:
        extra["memories_used"] = prefs
    if answer.key_terms:
        extra["key_terms"] = answer.key_terms
    yield from finish(trace, "web", answer.answer, citations, extra, answer.follow_ups)


def run(req: ChatRequest, cfg: LLMConfig, search_key: str | None = None, convo: Conversation | None = None) -> Iterator[Event]:
    """Guard → rewrite → cache → route → retrieve (or deep research) → rerank → (chart, calculate)
    → answer → verify → (web fallback) → cache → trace."""
    opts = req.settings
    trace = Trace(owner=convo.owner if convo else None)
    deep = req.deep
    web_ok = bool(opts.use_web_search and search_key)
    try:
        if opts.token_budget_remaining is not None and opts.token_budget_remaining <= 0:
            yield "error", {"message": "Session token budget used up. Raise it in Settings to continue."}
            return

        # 1. Input guardrails (free).
        question = req.question.strip()
        if opts.use_guardrails:
            with trace.step("guard"):
                g = check_input(question)
            question = g.text
            trace.question = question
            if not g.allowed:
                trace.route = "refusal"
                yield from finish(trace, "refusal", g.reason, [])
                return
        trace.question = question

        doc_ids = req.doc_ids or []  # the API passes exactly the documents this user may search
        if not doc_ids:
            yield "error", {"message": "No documents are indexed yet. Upload a PDF on the Documents page."}
            return
        filenames = {d["id"]: d["filename"] for d in documents.list_all()}
        # Deep answers differ from normal ones, so they never share cache rows.
        docset = semantic_cache.docset_key(doc_ids + (["deep"] if deep else []))
        # Session context: stored turns (bounded: summary + recent window) win over client-sent history.
        if convo is not None and convo.session_id:
            history, summary = convo.recent, convo.summary
        else:
            history, summary = [t.model_dump() for t in req.history][-8:], ""

        # 2. Rewrite follow-ups into a standalone query (small model; skipped on the first turn).
        query = question
        if history or summary:
            yield step("rewrite", "Understanding follow-up…")
            with trace.step("rewrite"):
                query, r = rewrite_query(question, history, cfg, summary)
            trace.add(r)

        # Cross-chat memory (opt-in): relevant user preferences, looked up locally (no tokens).
        prefs: list[str] = []
        if opts.use_memory and convo is not None:
            with trace.step("memory"):
                prefs = user_memory.relevant(convo.owner, query)

        # 3. Semantic cache, keyed on the standalone query + document set.
        query_vec = None
        if opts.use_cache:
            yield step("cache", "Checking cache…")
            with trace.step("cache"):
                query_vec = embed_query(query)
                hit = semantic_cache.lookup(docset, query_vec)
            if hit and not prefs:  # personalised answers are not served from the shared cache
                trace.cache_hit, trace.route = True, "cached"
                yield from finish(
                    trace, hit["answer_type"], hit["answer"], hit["citations"], {"query": query}, hit.get("follow_ups"), hit.get("chart")
                )
                return

        # 4. Route: intent + complexity → tier. Deep research always uses the large tier.
        yield step("route", "Routing question…")
        with trace.step("route"):
            r, r_llm = route(query, cfg)
        trace.add(r_llm)
        if deep:
            r = Route(r.intent, r.needs_calc, "high", "large", r.source, r.needs_chart)
        trace.intent, trace.complexity = r.intent, r.complexity
        if r.intent == "greeting":
            trace.route = "out_of_scope"
            yield from finish(trace, "out_of_scope", GREETING_MESSAGE, [])
            return
        if r.intent == "out_of_scope":
            if web_ok:
                yield from answer_from_web(query, r.tier, cfg, search_key, deep, trace, "outside the documents", prefs, opts.explain_terms)
            else:
                trace.route = "out_of_scope"
                yield from finish(trace, "out_of_scope", SCOPE_MESSAGE, [])
            return

        # 5. Retrieval: hybrid + rerank (or deep research over sub-questions), then the abstain gate.
        search_q = retrieval_query(query)
        if deep:
            yield step("plan", "Planning research…")
            with trace.step("plan"):
                subs, p_llm = deep_research.plan(query, cfg)
            trace.add(p_llm)
            for i, sq in enumerate(subs, start=1):
                yield step("research", f"Researching {i}/{len(subs)}: {sq}")
            with trace.step("retrieve"):
                top = deep_research.research(search_q, subs, doc_ids)
        else:
            yield step("retrieve", "Retrieving…")
            with trace.step("retrieve"):
                candidates = hybrid_search(search_q, doc_ids)
            yield step("rerank", "Reranking…")
            with trace.step("rerank"):
                top = rerank(search_q, candidates, opts.top_k)
        trace.chunk_ids = [c.chunk_id for c in top]
        if not passes_threshold(top):
            if web_ok:
                yield from answer_from_web(query, r.tier, cfg, search_key, deep, trace, "not in the documents", prefs, opts.explain_terms)
            else:
                trace.route = "not_found"
                yield from finish(trace, "not_found", NOT_FOUND, [])
            return

        context, labelled = build_context(top, filenames)
        chunk_texts = {label: c.text for label, c in labelled.items()}

        # 6. Optional chart and calculation: the LLM extracts numbers, Python checks/computes them.
        chart = None
        if r.needs_chart:
            yield step("chart", "Building chart…")
            with trace.step("chart"):
                chart, ch_llm, _note = build_chart(query, context, chunk_texts, cfg)
            trace.add(ch_llm)
        calc = None
        if r.needs_calc:
            yield step("calculate", "Calculating…")
            with trace.step("calculate"):
                calc, c_llm, _note = calculate(query, context, chunk_texts, cfg)
            trace.add(c_llm)

        # 7. Grounded answer, then deterministic verification (one stricter retry).
        problems: list[str] | None = None
        answer = None
        for attempt in range(2):
            yield step("answer", ("Writing research answer…" if deep else "Writing answer…") if attempt == 0 else "Retrying with stricter rules…")
            with trace.step("answer"):
                answer, calls = generate_answer(query, context, r.tier, cfg, calc.as_prompt() if calc else None, problems, deep=deep, preferences=prefs, explain_terms=opts.explain_terms)
            trace.add(*calls)
            trace.model = calls[-1].model if calls else trace.model
            if answer.unanswerable:
                break
            yield step("verify", "Verifying…")
            cited = list(dict.fromkeys(answer.citations + CITATION.findall(answer.answer)))
            calc_values = [calc.value] + [i["value"] for i in calc.inputs] if calc else []
            with trace.step("verify"):
                v = verify_answer(answer.answer, cited, chunk_texts, question=query, calc_values=calc_values)
            if v.ok:
                trace.verification = "pass" if attempt == 0 else "retry_pass"
                break
            problems = v.problems
            trace.verification = "fail"

        if answer is None or answer.unanswerable or trace.verification == "fail":
            if web_ok:
                trace.verification = "skipped"
                yield from answer_from_web(query, r.tier, cfg, search_key, deep, trace, "not answerable from the documents", prefs, opts.explain_terms)
            else:
                trace.route = "not_found"
                yield from finish(trace, "not_found", NOT_FOUND, [])
            return

        # 8. Optional LLM judge, only where it's worth the tokens.
        if opts.use_judge and r.complexity == "high":
            yield step("judge", "Checking faithfulness…")
            with trace.step("judge"):
                trace.judge, j_llm = judge(answer.answer, context, cfg)
            trace.add(j_llm)

        cited = list(dict.fromkeys(answer.citations + CITATION.findall(answer.answer)))
        if chart:  # chart points cite chunks too; make those pages openable
            cited += [p["chunk"] for s in chart["series"] for p in s["points"] if p["chunk"] not in cited]
        citations = [doc_citation(label, labelled[label], filenames) for label in dict.fromkeys(cited) if label in labelled]
        client_chart = chart_for_client(chart, labelled) if chart else None
        trace.route = "answer"
        if opts.use_cache and query_vec is not None and not prefs:
            semantic_cache.store(
                docset,
                query,
                query_vec,
                {"answer": answer.answer, "answer_type": "answer", "citations": citations, "follow_ups": answer.follow_ups, "chart": client_chart},
            )
        extra: dict = {"query": query, "deep": deep}
        if calc:
            extra["calculation"] = {"label": calc.label, "value": calc.value, "unit": calc.unit, "expression": calc.expression}
        if trace.judge:
            extra["judge"] = trace.judge
        if prefs:
            extra["memories_used"] = prefs
        if answer.key_terms:
            extra["key_terms"] = answer.key_terms
        yield from finish(trace, "answer", answer.answer, citations, extra, answer.follow_ups, client_chart)

    except LLMError as exc:
        trace.route = "error"
        trace.save()
        yield "error", {"message": mask(str(exc), cfg.secrets())}
    except Exception as exc:
        trace.route = "error"
        trace.save()
        yield "error", {"message": f"Unexpected error: {type(exc).__name__}"}

"""Follow-up → standalone query."""

from ..llm.gateway import LLMConfig, LLMResult, complete, parse_json

PROMPT = """Rewrite the user's latest question as one standalone question that can be understood without the conversation.
Resolve pronouns and references ("it", "that year", "what about 2023?") using the conversation.
Keep company names, years, segments and metrics explicit. Do not answer the question.
Return only JSON: {"query": "<standalone question>"}"""


def rewrite_query(question: str, history: list[dict], cfg: LLMConfig, summary: str = "") -> tuple[str, LLMResult | None]:
    """Use the last 4 turns to make a follow-up self-contained, with the small model.

    Why before retrieval: the retriever only sees the query string. "What about 2023?"
    retrieves nothing useful; "What was Berkshire's float in 2023?" does.
    Skipped on the first turn (nothing to resolve), and falls back to the raw question on failure.
    """
    if not history and not summary:
        return question, None
    convo = "\n".join(f"{t['role']}: {t['content'][:1000]}" for t in history)
    earlier = f"<earlier_summary>\n{summary}\n</earlier_summary>\n" if summary else ""
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"{earlier}<conversation>\n{convo}\n</conversation>\n\nLatest question: {question}"},
    ]
    try:
        result = complete("small", messages, cfg, json_mode=True, max_tokens=150)
        query = str(parse_json(result.text).get("query", "")).strip()
        return (query or question), result
    except Exception:
        return question, None

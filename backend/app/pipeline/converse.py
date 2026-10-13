"""Conversational replies: greetings, questions about the assistant or the loaded documents, feedback,
requests too vague to search, and questions outside the reports.

Why a separate step: not every message is a document lookup. Answering "hi" or "which documents do you
have?" with "Not found in the provided documents" is correct but useless. These replies never state
facts about a company, so the grounding rules still hold, and a code check enforces it.
"""

from dataclasses import dataclass, field

from ..llm.gateway import LLMConfig, LLMResult, complete, parse_json
from .verify import extract_numbers, matches

PROMPT = """You are FinCite, a friendly analyst assistant for company annual reports and financial filings.
Every fact and figure you give comes from the user's own documents, with a page citation. This message is
conversational, so this reply contains no facts about any company.

Reply naturally, warmly and briefly (1-3 sentences), in the user's language:
- Greetings, thanks, small talk: respond in kind and invite a question about their documents.
- Questions about you or what you can do: you find answers in their reports and cite the page, compute
  figures such as growth and ratios in code, draw charts of trends, and say plainly when the documents
  don't cover something instead of guessing.{web_line}
- Which documents are loaded: list them from DOCUMENTS. If there are none, ask them to upload one on the
  Documents page.
- A request too vague to search (no metric, period, company or topic): ask ONE short question to get what
  you need, offering 2-3 concrete options.
- Frustration or "why didn't you answer": acknowledge it briefly, then help: name the metric and year, and
  use the report's own wording (reports often say "net sales" or "profit after tax" rather than "revenue"
  or "profit").
{scope_line}
- Never state facts, figures or claims about any company, even well-known ones. Never invent document
  contents beyond the names in DOCUMENTS.
"suggestions": up to 3 short questions the user could ask about their documents (from the document names
only); [] if there are no documents.
Return only JSON: {{"reply": "...", "suggestions": ["...", "..."]}}"""

SCOPE_LINE = (
    "- Questions unrelated to the reports (general knowledge, coding, personal advice): say kindly that you only "
    "answer from their documents{web_hint}, and suggest a question about the documents instead."
)

FALLBACK = {
    "chat": "Hi! I answer questions about your uploaded reports and cite the page for every figure. What would you like to know?",
    "out_of_scope": "I can only answer from your uploaded reports, so I can't help with that one. Ask me anything about your documents.",
}


@dataclass
class Reply:
    text: str
    suggestions: list[str] = field(default_factory=list)


def _facts_free(text: str, allowed: str) -> bool:
    """No figures except those the user typed or the document list shows (names, page counts).
    Small integers (≤ 10) are fine: "3 documents", "2 options"."""
    sources = [v for v, _ in extract_numbers(allowed)]
    return all(
        (decimals == 0 and value <= 10) or any(matches(value, decimals, s) for s in sources)
        for value, decimals in extract_numbers(text)
    )


def converse(
    question: str,
    kind: str,
    documents: list[dict],
    history: list[dict],
    cfg: LLMConfig,
    web_available: bool = False,
) -> tuple[Reply, LLMResult | None]:
    """kind: 'chat' (conversational) or 'out_of_scope'. Small model; falls back to a fixed reply on failure."""
    docs = "\n".join(f"- {d['filename']} ({d.get('pages') or '?'} pages)" for d in documents) or "(none uploaded yet)"
    web_hint = " (or from the web, when web search is switched on)" if web_available else ", or from the web if they switch on Web in the question box"
    system = PROMPT.format(
        web_line=" When web search is on, you can also answer from the web, clearly labelled." if web_available else "",
        scope_line=SCOPE_LINE.format(web_hint=web_hint),
    )
    convo = "\n".join(f"{t['role']}: {t['content'][:600]}" for t in history[-6:])
    user = f"DOCUMENTS:\n{docs}\n\n" + (f"<conversation>\n{convo}\n</conversation>\n\n" if convo else "") + f"User: {question}"
    try:
        result = complete("small", [{"role": "system", "content": system}, {"role": "user", "content": user}], cfg, json_mode=True, max_tokens=400)
        data = parse_json(result.text)
        text = " ".join(str(data.get("reply", "")).split())
        suggestions = [" ".join(str(s).split())[:160] for s in data.get("suggestions", []) if str(s).strip()][:3] if documents else []
    except Exception:
        return Reply(FALLBACK[kind]), None
    if not text or not _facts_free(text, f"{docs}\n{question}"):
        return Reply(FALLBACK[kind], suggestions), result
    return Reply(text, suggestions), result

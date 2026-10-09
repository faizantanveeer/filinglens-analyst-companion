"""Web search fallback (Tavily), used only when the documents can't answer."""

import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from ..config import settings
from .guard_input import looks_like_injection

TAVILY_URL = "https://api.tavily.com/search"


class WebSearchError(Exception):
    pass


def tavily_search(query: str, key: str, max_results: int | None = None) -> list[dict]:
    """[{title, url, content}] from Tavily. Plain HTTPS POST, so no extra dependency.

    The key arrives per request (X-Search-Key) like the LLM key, and is never stored or logged.
    """
    body = json.dumps(
        {
            "query": query[:400],
            "max_results": max_results or settings.web_results,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }
    ).encode()
    req = urllib.request.Request(
        TAVILY_URL,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        reason = {401: "invalid Tavily key", 429: "Tavily rate limit reached", 432: "Tavily plan limit reached"}.get(exc.code, f"HTTP {exc.code}")
        raise WebSearchError(f"Web search failed: {reason}.") from None
    except Exception as exc:
        raise WebSearchError(f"Web search failed: {type(exc).__name__}.") from None
    return [
        {"title": str(r.get("title") or "")[:200], "url": str(r.get("url") or ""), "content": str(r.get("content") or "")[:2500]}
        for r in data.get("results", [])
        if str(r.get("url", "")).startswith(("http://", "https://"))
    ]


def build_web_context(results: list[dict]) -> tuple[str, dict[str, dict]]:
    """Label results W1..Wn and wrap them in <context>, treating page text as untrusted data
    (same escaping and injection flag as document chunks)."""
    labelled, parts = {}, []
    for i, r in enumerate(results, start=1):
        label = f"W{i}"
        suspicious = looks_like_injection(r["content"])
        labelled[label] = {**r, "suspicious": suspicious}
        text = r["content"].replace("<", "‹").replace(">", "›")
        title = r["title"].replace('"', "'").replace("<", "‹")
        attrs = f'id="{label}" site="{urlsplit(r["url"]).hostname}" title="{title}"'
        if suspicious:
            attrs += ' suspicious="true"'
        parts.append(f"<source {attrs}>\n{text}\n</source>")
    return "<context>\n" + "\n".join(parts) + "\n</context>", labelled

"""Grounded charts: the LLM proposes data points, Python keeps only the ones the documents contain."""

import re

from ..llm.gateway import LLMConfig, LLMResult, complete, parse_json
from .verify import number_in_text

MAX_SERIES = 4  # beyond four, colours stop being distinguishable; fold or facet instead
MAX_POINTS = 24

PROMPT = """You extract data for a chart from <context>; you do NOT invent or compute values.
Find the values that answer the question across periods (years, quarters) or categories (segments, businesses).
- Copy each value exactly as printed (drop thousands separators; keep the document's scale, e.g. "in millions").
- "x" is the period or category label as printed (e.g. "2023", "Q4 2022", "BNSF").
- "chunk" is the id of the <context> item containing that value.
- At most 4 series and 24 points per series. Use one series unless the question compares several measures.
- "kind": "line" for values over time, "bar" for categories.
If fewer than 2 values are available, return {"series": []}.
Return only JSON:
{"title": "...", "kind": "line", "unit": "USD millions", "series": [{"name": "...", "points": [{"x": "2022", "y": 164109, "chunk": "C1"}]}]}"""

YEAR = re.compile(r"^(19|20)\d\d$")


def build_chart(question: str, context: str, chunk_texts: dict[str, str], cfg: LLMConfig) -> tuple[dict | None, LLMResult | None, str]:
    """Return (chart or None, llm usage, note).

    Why verify every point: a chart is a set of numbers presented as fact. Each value must
    appear in the chunk it cites, exactly like calculator inputs; unverifiable points are dropped
    and a series with fewer than 2 surviving points is not drawn at all.
    """
    messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": f"{context}\n\nQuestion: {question}"}]
    try:
        llm = complete("small", messages, cfg, json_mode=True, max_tokens=900)
        data = parse_json(llm.text)
    except Exception as exc:
        return None, None, f"extraction failed: {type(exc).__name__}"

    series_out, dropped = [], 0
    for s in (data.get("series") or [])[:MAX_SERIES]:
        points, seen_x = [], set()
        for p in (s.get("points") or [])[:MAX_POINTS]:
            x, chunk = str(p.get("x", "")).strip()[:40], str(p.get("chunk", ""))
            try:
                y = float(str(p.get("y")).replace(",", ""))
            except ValueError:
                dropped += 1
                continue
            if not x or x in seen_x or chunk not in chunk_texts or not number_in_text(y, chunk_texts[chunk]):
                dropped += 1
                continue
            seen_x.add(x)
            points.append({"x": x, "y": y, "chunk": chunk})
        if len(points) >= 2:
            if all(YEAR.match(p["x"]) for p in points):
                points.sort(key=lambda p: int(p["x"]))  # time runs left to right
            series_out.append({"name": str(s.get("name") or "Value")[:60], "points": points})

    if not series_out:
        return None, llm, f"no verifiable series ({dropped} points dropped)"
    kind = data.get("kind") if data.get("kind") in ("line", "bar") else "line"
    chart = {
        "title": str(data.get("title") or question)[:120],
        "kind": kind,
        "unit": str(data.get("unit") or "")[:40],
        "series": series_out,
        "dropped_points": dropped,
    }
    return chart, llm, "ok"

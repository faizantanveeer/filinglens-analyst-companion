"""Intent + complexity → model tier."""

import re
from dataclasses import dataclass

from ..llm.gateway import LLMConfig, LLMResult, complete, parse_json
from ..schemas import RouteJSON

GREETING = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|good (morning|afternoon|evening))\b[\s!.?]*$", re.I)
CHART_WORDS = re.compile(
    r"\b(trends?|over (the )?(years|time|period)|year[- ]over[- ]year|history|historical|charts?|plot|graphs?|visuali[sz]e|"
    r"each year|by year|per year|since (19|20)\d\d|from (19|20)\d\d to (19|20)\d\d|breakdown)\b",
    re.I,
)
# Presentation wording ("plot", "show me a chart of") says how to display the answer, not what to find.
# Left in, it pulls the cross-encoder's score down by ~2 on the eval report and can trip the abstain gate.
PRESENTATION = re.compile(
    r"\b(please\s+)?(plot|chart|graph|visuali[sz]e|draw|show( me)?|display|make|create|give me)\b"
    r"(\s+(a|an|the))?(\s+(line|bar))?(\s+(chart|graph|plot))?(\s+(of|for|showing))?\s*",
    re.I,
)


def retrieval_query(query: str) -> str:
    """The query used for search: presentation words removed, content words kept."""
    cleaned = " ".join(PRESENTATION.sub(" ", query).split())
    return cleaned if len(cleaned) >= 3 else query


CALC_WORDS = re.compile(
    r"\b(grow|growth|grew|increase|decrease|decline|change|differen|ratio|margin|percent|%|cagr|times|sum|total of|combined)\w*",
    re.I,
)

PROMPT = """Classify a question asked about uploaded company annual reports.
- intent: "lookup" (find a fact), "compare" (compare items or periods), "summarize" (overview of a topic),
  or "out_of_scope" (not answerable from a company's annual report: general knowledge, coding, chit-chat, advice).
- needs_calc: true if the answer requires arithmetic on reported numbers (growth %, ratio, difference, sum, margin).
- needs_chart: true if the question asks for a trend, history, breakdown or values across several periods or segments
  that would be clearer as a chart (e.g. "how has X changed since 2019", "plot revenue by segment").
- complexity: "low" for a single fact lookup; "high" for comparisons, summaries, multi-part questions or calculations.
Return only JSON: {"intent": "...", "needs_calc": true|false, "needs_chart": true|false, "complexity": "low"|"high"}"""


@dataclass
class Route:
    intent: str
    needs_calc: bool
    complexity: str
    tier: str
    source: str  # heuristic | llm | fallback
    needs_chart: bool = False


def route(query: str, cfg: LLMConfig) -> tuple[Route, LLMResult | None]:
    """Free heuristics first, then a small-model JSON classification.

    Why fail toward the large tier: if classification breaks, spending a few more tokens
    is better than answering a hard question with the weak model.
    """
    if not query.strip():
        return Route("out_of_scope", False, "low", "small", "heuristic"), None
    if GREETING.match(query):
        return Route("greeting", False, "low", "small", "heuristic"), None
    if len(query) > 400:  # long, multi-part questions: skip the classifier, use the strong model
        return Route("summarize", bool(CALC_WORDS.search(query)), "high", "large", "heuristic", bool(CHART_WORDS.search(query))), None

    messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": query}]
    try:
        result = complete("small", messages, cfg, json_mode=True, max_tokens=80)
        parsed = RouteJSON.model_validate(parse_json(result.text))
        tier = "small" if parsed.complexity == "low" and not parsed.needs_calc else "large"
        # The keyword check backs up the classifier: a missed chart costs more than an extra one.
        chart = parsed.needs_chart or bool(CHART_WORDS.search(query))
        return Route(parsed.intent, parsed.needs_calc, parsed.complexity, tier, "llm", chart), result
    except Exception:
        return Route("lookup", bool(CALC_WORDS.search(query)), "high", "large", "fallback", bool(CHART_WORDS.search(query))), None

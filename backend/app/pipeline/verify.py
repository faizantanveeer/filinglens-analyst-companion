"""Deterministic answer verification: citations and numbers. No LLM calls (except the optional judge)."""

import re
from dataclasses import dataclass, field

from ..llm.gateway import LLMConfig, LLMResult, complete, parse_json

CITATION = re.compile(r"\[([CW]\d+)\]")  # C# = document chunk, W# = web source
NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
SCALES = (1, 1e3, 1e6, 1e9, 1e-3, 1e-6, 1e-9)


def extract_numbers(text: str) -> list[tuple[float, int]]:
    """[(value, decimals shown)]. Citation markers like [C2] are removed first."""
    out = []
    for m in NUMBER.finditer(CITATION.sub(" ", text)):
        raw = m.group().rstrip(",").replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        out.append((value, decimals))
    return out


def matches(answer_value: float, decimals: int, source: float) -> bool:
    """True if the answer number is the source number, possibly rescaled and rounded.

    "37.4 billion" matches "37,350" (millions): 37,350 / 1e3 = 37.35, which rounds to 37.4
    at one decimal. Tolerance is half a unit of the displayed precision, at any 10^3k scale.
    """
    tolerance = 0.5 * 10 ** (-decimals) + 1e-9
    source = abs(source)  # signs are written many ways ("-3.2%", "(3.2)", "a decline of 3.2%")
    return any(abs(source / s - answer_value) <= tolerance for s in SCALES)


def number_in_text(value: float, text: str) -> bool:
    """Exact (unscaled, unrounded) presence check, used to ground calculator inputs and chart points.
    Compared without sign, since documents write negatives as "(30)" or "decline of 30"."""
    return any(abs(v - abs(value)) < 1e-9 for v, _ in extract_numbers(text))


@dataclass
class Verification:
    ok: bool
    problems: list[str] = field(default_factory=list)


def verify_answer(
    answer: str,
    cited: list[str],
    context_texts: dict[str, str],
    question: str = "",
    calc_values: list[float] | None = None,
) -> Verification:
    """1) every cited id was retrieved; 2) every number appears in a cited chunk or is a calculator output.

    Why code, not an LLM: these checks are free, instant and deterministic. They can't be
    persuaded, and they catch the most expensive failure in finance: a wrong number.
    Small integers (≤ 10) are allowed, since "two segments" or "3 reasons" aren't facts worth blocking.
    """
    problems = []
    unknown = [c for c in cited if c not in context_texts]
    if unknown:
        problems.append(f"cited ids not in context: {', '.join(unknown)}")
    if not cited:
        problems.append("no citations")

    sources = [v for c in cited if c in context_texts for v, _ in extract_numbers(context_texts[c])]
    sources += [v for v, _ in extract_numbers(question)]
    sources += calc_values or []
    for value, decimals in extract_numbers(answer):
        if decimals == 0 and value <= 10:
            continue
        if not any(matches(value, decimals, s) for s in sources):
            problems.append(f"number {value:g} not found in cited chunks")
    return Verification(not problems, problems)


JUDGE_PROMPT = """You check an answer against its source context.
Is every claim in ANSWER supported by CONTEXT? Ignore style; focus on facts and numbers.
Return only JSON: {"faithful": true|false, "reason": "<one short sentence>"}"""


def judge(answer: str, context: str, cfg: LLMConfig) -> tuple[dict | None, LLMResult | None]:
    """Optional small-model faithfulness rating, only for complexity=high (where it's worth the tokens)."""
    messages = [
        {"role": "system", "content": JUDGE_PROMPT},
        {"role": "user", "content": f"{context}\n\nANSWER:\n{answer}"},
    ]
    try:
        result = complete("small", messages, cfg, json_mode=True, max_tokens=120)
        data = parse_json(result.text)
        return {"faithful": bool(data.get("faithful")), "reason": str(data.get("reason", ""))[:300]}, result
    except Exception:
        return None, None

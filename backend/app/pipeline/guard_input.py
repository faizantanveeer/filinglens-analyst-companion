"""Input guardrails: length, prompt injection, PII redaction. Pure regex, no LLM calls."""

import re
from dataclasses import dataclass

from ..config import settings

# Attempts to override instructions or extract the system prompt. Also used at ingest time
# to flag document chunks that try to talk to the model.
INJECTION_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|prompts?|rules)",
    r"disregard (all |any )?(the )?(previous|prior|above|earlier|your) (instructions|prompts?|rules)",
    r"forget (all |everything|your) (previous |prior )?(instructions|rules)",
    r"(reveal|show|print|repeat|output|tell me) (me )?(your|the) (system|hidden|initial) (prompt|instructions|message)",
    r"what (is|are) your (system )?(prompt|instructions)",
    r"you are now (a|an|in) ",
    r"\bact as (a|an) (?!analyst)",
    r"\b(developer|dan|jailbreak) mode\b",
    r"new instructions\s*:",
    r"</?(system|context|instructions)>",
]
_INJECTION = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)

# PII: emails, phone numbers, card-like numbers (13–19 digits with optional separators).
PII_PATTERNS = {
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "CARD": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "PHONE": re.compile(r"(?<!\w)(?:\+?\d{1,3}[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}\b"),
}


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text))


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Replace PII with placeholders before anything reaches the LLM or the trace log."""
    found = []
    for label, pattern in PII_PATTERNS.items():
        if pattern.search(text):
            found.append(label)
            text = pattern.sub(f"[{label}]", text)
    return text, found


@dataclass
class GuardResult:
    allowed: bool
    text: str
    reason: str = ""
    redacted: tuple[str, ...] = ()


def check_input(question: str) -> GuardResult:
    """Run the free, deterministic checks before spending any tokens.

    Why: blocking here costs nothing and can't be talked around the way an LLM can.
    """
    q = question.strip()
    if len(q) > settings.max_question_chars:
        return GuardResult(False, q, f"Questions are limited to {settings.max_question_chars} characters.")
    if looks_like_injection(q):
        return GuardResult(False, q, "I can only answer questions about your uploaded documents.")
    redacted, found = redact_pii(q)
    return GuardResult(True, redacted, redacted=tuple(found))

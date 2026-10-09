"""Arithmetic in Python, never in the LLM."""

import ast
import operator
from dataclasses import dataclass

from ..llm.gateway import LLMConfig, LLMResult, complete, parse_json
from .verify import number_in_text

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def safe_eval(expression: str, variables: dict[str, float]) -> float:
    """Evaluate + - * / ** and parentheses over named numbers by walking the AST.

    Why not eval(): the expression comes from an LLM, which can be steered by document text.
    Only whitelisted node types are allowed, so there's no attribute access, calls or imports.
    """

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"unknown name {node.id}")
            return float(variables[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10:
                raise ValueError("exponent too large")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError(f"disallowed expression element: {type(node).__name__}")

    if len(expression) > 200:
        raise ValueError("expression too long")
    return ev(ast.parse(expression, mode="eval"))


@dataclass
class CalcResult:
    label: str
    value: float
    unit: str
    expression: str
    inputs: list[dict]  # [{name, label, value, unit, chunk}]

    def as_prompt(self) -> str:
        parts = ", ".join(f"{i['name']} = {i['label']} = {i['value']} {i['unit']} [{i['chunk']}]" for i in self.inputs)
        return f"{self.label} = {self.value:,.2f} {self.unit} (computed in Python as {self.expression}, where {parts})"


PROMPT = """You prepare a calculation; you do NOT perform it.
From <context>, extract every number needed to answer the question, copying each value exactly as printed
(drop thousands separators, keep the scale stated in the document, e.g. "in millions").
Name them a, b, c, ... and write an arithmetic expression over those names using only + - * / ** and parentheses.
For percentage change use (new - old) / old * 100.
Return only JSON:
{"numbers": [{"name": "a", "label": "...", "value": 123.4, "unit": "...", "chunk": "C1"}],
 "expression": "(b - a) / a * 100", "result_label": "...", "result_unit": "%"}
If the context lacks a needed number, return {"numbers": [], "expression": ""}."""


def calculate(question: str, context: str, chunk_texts: dict[str, str], cfg: LLMConfig) -> tuple[CalcResult | None, LLMResult | None, str]:
    """LLM extracts {label, value, unit, chunk}; Python checks each value is really in its chunk, then computes.

    Returns (result or None, llm usage, note). A None result means the answer step proceeds
    without a calculation, and verification will reject any number the model invents.
    """
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"{context}\n\nQuestion: {question}"},
    ]
    try:
        llm = complete("small", messages, cfg, json_mode=True, max_tokens=400)
        data = parse_json(llm.text)
    except Exception as exc:
        return None, None, f"extraction failed: {type(exc).__name__}"

    numbers = data.get("numbers") or []
    expression = str(data.get("expression") or "")
    if not numbers or not expression:
        return None, llm, "context lacks the numbers"

    variables: dict[str, float] = {}
    for n in numbers:
        name, chunk = str(n.get("name", "")), str(n.get("chunk", ""))
        try:
            value = float(str(n.get("value")).replace(",", ""))
        except ValueError:
            return None, llm, f"non-numeric value for {name}"
        # Grounding: the extracted value must actually appear in the chunk it claims to come from.
        if chunk not in chunk_texts or not number_in_text(value, chunk_texts[chunk]):
            return None, llm, f"value {value} not found in {chunk}"
        variables[name] = value
    try:
        result = safe_eval(expression, variables)
    except (ValueError, ZeroDivisionError, SyntaxError, OverflowError) as exc:
        return None, llm, f"expression rejected: {exc}"

    calc = CalcResult(
        label=str(data.get("result_label") or "Result"),
        value=round(result, 4),
        unit=str(data.get("result_unit") or ""),
        expression=expression,
        inputs=[{**n, "value": variables[str(n["name"])]} for n in numbers],
    )
    return calc, llm, "ok"

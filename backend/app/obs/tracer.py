"""Per-request trace → one SQLite row. Feeds the Insights page and the eval report."""

import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..db import tx
from ..llm.gateway import LLMResult


@dataclass
class Trace:
    """Collects what happened in one request. Holds no secrets: the question is already PII-redacted."""

    question: str = ""
    owner: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started: float = field(default_factory=time.perf_counter)
    route: str = ""
    intent: str = ""
    complexity: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    steps: dict = field(default_factory=dict)  # step name → ms
    chunk_ids: list = field(default_factory=list)
    cache_hit: bool = False
    verification: str = "skipped"
    judge: dict | None = None

    @contextmanager
    def step(self, name: str):
        t = time.perf_counter()
        try:
            yield
        finally:
            self.steps[name] = self.steps.get(name, 0) + round((time.perf_counter() - t) * 1000)

    def add(self, *results: LLMResult | None) -> None:
        for r in results:
            if r:
                self.input_tokens += r.input_tokens
                self.output_tokens += r.output_tokens
                self.cost += r.cost

    @property
    def latency_ms(self) -> int:
        return round((time.perf_counter() - self.started) * 1000)

    def usage(self) -> dict:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "cost": round(self.cost, 6)}

    def save(self) -> None:
        with tx() as c:
            c.execute(
                """INSERT INTO traces (id, created_at, question, route, intent, complexity, model, input_tokens,
                   output_tokens, cost, latency_ms, steps, chunk_ids, cache_hit, verification, judge, owner)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.id,
                    datetime.now(timezone.utc).isoformat(),
                    self.question[:500],
                    self.route,
                    self.intent,
                    self.complexity,
                    self.model,
                    self.input_tokens,
                    self.output_tokens,
                    self.cost,
                    self.latency_ms,
                    json.dumps(self.steps),
                    json.dumps(self.chunk_ids),
                    int(self.cache_hit),
                    self.verification,
                    json.dumps(self.judge) if self.judge else None,
                    self.owner,
                ),
            )


def percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def insights(limit_recent: int = 20, owner: str | None = None) -> dict:
    """Aggregates for the Insights page; with an owner, only that browser's requests."""
    with tx() as c:
        if owner is None:
            rows = [dict(r) for r in c.execute("SELECT * FROM traces ORDER BY created_at DESC").fetchall()]
        else:
            rows = [dict(r) for r in c.execute("SELECT * FROM traces WHERE owner = ? ORDER BY created_at DESC", (owner,)).fetchall()]
    n = len(rows)
    latencies = [r["latency_ms"] for r in rows]
    routes: dict[str, int] = {}
    step_totals: dict[str, list[int]] = {}
    for r in rows:
        routes[r["route"] or "unknown"] = routes.get(r["route"] or "unknown", 0) + 1
        for name, ms in json.loads(r["steps"] or "{}").items():
            step_totals.setdefault(name, []).append(ms)
    return {
        "requests": n,
        "total_cost": round(sum(r["cost"] for r in rows), 6),
        "avg_tokens": round(sum(r["input_tokens"] + r["output_tokens"] for r in rows) / n, 1) if n else 0,
        "cache_hit_rate": round(sum(r["cache_hit"] for r in rows) / n, 3) if n else 0,
        "p50_latency_ms": percentile(latencies, 50),
        "p95_latency_ms": percentile(latencies, 95),
        "routes": [{"route": k, "count": v} for k, v in sorted(routes.items(), key=lambda kv: -kv[1])],
        "step_latency": [{"step": k, "avg_ms": round(sum(v) / len(v))} for k, v in step_totals.items()],
        "recent": [
            {
                k: r[k]
                for k in ("id", "created_at", "question", "route", "model", "input_tokens", "output_tokens", "cost", "latency_ms", "cache_hit", "verification")
            }
            for r in rows[:limit_recent]
        ],
    }

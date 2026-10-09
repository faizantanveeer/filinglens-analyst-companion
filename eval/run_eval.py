"""Evaluate retrieval and answers on eval/golden.jsonl; write eval/results.md.

Retrieval metrics (Hit@5, MRR, threshold sweep) are local and free.
Answer metrics need an LLM: set EVAL_PROVIDER, EVAL_SMALL_MODEL, EVAL_LARGE_MODEL and EVAL_LLM_KEY
(the key is read from the environment for this run only, never written anywhere).

    python eval/run_eval.py                     # retrieval only
    python eval/run_eval.py --min-score -2.0    # evaluate with a different abstain threshold
"""

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# A dedicated index so the eval never touches the app's data.
os.environ.setdefault("DATA_DIR", str(ROOT / ".index"))
sys.path.insert(0, str(ROOT.parent))

from backend.app import documents  # noqa: E402
from backend.app.config import settings  # noqa: E402
from backend.app.ingest.indexer import client  # noqa: E402
from backend.app.llm.gateway import LLMConfig  # noqa: E402
from backend.app.pipeline import orchestrator  # noqa: E402
from backend.app.retrieval.hybrid import hybrid_search  # noqa: E402
from backend.app.retrieval.rerank import passes_threshold, rerank  # noqa: E402
from backend.app.schemas import ChatRequest  # noqa: E402
from backend.app.seed import fetch_sample  # noqa: E402

REPORT = ROOT / "data" / "report.pdf"
GOLDEN = ROOT / "golden.jsonl"
# Cloud mode (Jina reranker) scores 0..1; local cross-encoder logits span about -11..+10.
RESULTS = ROOT / ("results-cloud.md" if settings.cloud else "results.md")
SWEEP = [0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5] if settings.cloud else [-6.0, -4.0, -3.0, -2.0, -1.0, 0.0, 1.0, 2.0]


def ensure_indexed() -> str:
    fetch_sample(REPORT)  # the PDF isn't in the repo; download the public report on first run
    data = REPORT.read_bytes()
    digest = documents.sha256(data)
    doc = documents.find_by_hash(digest)
    if doc and doc["status"] == "ready":
        return doc["id"]
    doc_id = "evalreport"
    if doc:
        documents.delete(doc["id"])
    documents.register(doc_id, REPORT.name, digest)
    documents.save_file(doc_id, "pdf", data)
    print("Indexing report (one-time, a few minutes)…")
    documents.ingest(doc_id)
    if documents.get(doc_id)["status"] != "ready":
        sys.exit(f"Indexing failed: {documents.get(doc_id)['error']}")
    return doc_id


def retrieval_eval(golden: list[dict], doc_id: str, top_k: int) -> dict:
    """Hit@k and MRR on answerable questions; best rerank score per question for the threshold sweep."""
    hits, rr, best_scores = [], [], []
    for g in golden:
        ranked = rerank(g["question"], hybrid_search(g["question"], [doc_id]), top_k)
        best_scores.append((ranked[0].rerank_score if ranked else float("-inf"), g["answerable"]))
        if not g["answerable"]:
            continue
        pages = [c.page for c in ranked]
        first = next((i for i, p in enumerate(pages, 1) if p in g["expected_pages"]), None)
        hits.append(first is not None)
        rr.append(1 / first if first else 0.0)
    sweep = []
    for t in SWEEP:
        correct = sum((s >= t) == answerable for s, answerable in best_scores)
        false_abstain = sum(s < t and a for s, a in best_scores)
        sweep.append({"threshold": t, "abstention_accuracy": correct / len(best_scores), "false_abstains": false_abstain})
    return {"hit": sum(hits) / len(hits), "mrr": sum(rr) / len(rr), "sweep": sweep, "best_scores": best_scores}


def top_k_sweep(golden: list[dict], doc_id: str, ks=(3, 5, 8)) -> list[dict]:
    """Hit@k for several k: more chunks raise recall but cost context tokens on every answer."""
    rows = []
    answerable = [g for g in golden if g["answerable"]]
    for k in ks:
        hit = sum(
            any(c.page in g["expected_pages"] for c in rerank(g["question"], hybrid_search(g["question"], [doc_id]), k))
            for g in answerable
        )
        rows.append({"k": k, "hit": hit / len(answerable)})
    return rows


def answer_eval(golden: list[dict], doc_id: str, cfg: LLMConfig, provider: str, judge: bool) -> dict:
    rows = []
    for g in golden:
        req = ChatRequest(
            question=g["question"],
            doc_ids=[doc_id],
            settings={
                "provider": provider,
                "small_model": cfg.small_model,
                "large_model": cfg.large_model,
                "use_cache": False,
                "use_judge": judge,
            },
        )
        t = time.perf_counter()
        events = list(orchestrator.run(req, cfg))
        latency = (time.perf_counter() - t) * 1000
        done = next((d for e, d in events if e == "done"), None)
        error = next((d["message"] for e, d in events if e == "error"), None)
        text = "".join(d["text"] for e, d in events if e == "token")
        cites = next((d["citations"] for e, d in events if e == "citations"), [])
        rows.append({"g": g, "done": done, "error": error, "text": text, "cites": cites, "latency": latency})
        print(f"  {'OK ' if done else 'ERR'} {g['question'][:60]} → {(done or {}).get('answer_type', error)}")

    answerable = [r for r in rows if r["g"]["answerable"]]
    cited = [c for r in answerable for c in r["cites"]]
    abstain_ok = sum(
        (r["done"] or {}).get("answer_type") == ("answer" if r["g"]["answerable"] else "not_found") for r in rows
    )
    correct = sum(
        any(s.lower() in r["text"].lower() for s in r["g"]["expected_answer_contains"])
        for r in answerable
        if (r["done"] or {}).get("answer_type") == "answer"
    )
    judged = [r["done"]["judge"] for r in rows if r["done"] and r["done"].get("judge")]
    costs = [r["done"]["usage"]["cost"] for r in rows if r["done"]]
    return {
        "citation_precision": (sum(c["page"] in r["g"]["expected_pages"] for r in answerable for c in r["cites"]) / len(cited)) if cited else 0.0,
        "abstention_accuracy": abstain_ok / len(rows),
        "answer_accuracy": correct / len(answerable),
        "faithfulness": (sum(j["faithful"] for j in judged) / len(judged)) if judged else None,
        "avg_cost": sum(costs) / len(costs) if costs else 0.0,
        "p50_latency_ms": statistics.median(r["latency"] for r in rows),
        "errors": sum(1 for r in rows if r["error"]),
        "rows": rows,
    }


def write_results(ret: dict, ans: dict | None, top_k: int, cfg_line: str) -> None:
    lines = [
        "# FilingLens evaluation results",
        "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} on `{REPORT.name}` with {sum(1 for _ in GOLDEN.open())} golden questions.",
        f"Config: top_k={top_k}, MIN_RERANK_SCORE={settings.min_rerank_score}, {cfg_line}",
        "",
        "## Retrieval (local, no LLM)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Hit@{top_k} | {ret['hit']:.2f} |",
        f"| MRR | {ret['mrr']:.2f} |",
        "",
        "## Abstain-threshold sweep (top rerank score vs. answerable)",
        "",
        "| MIN_RERANK_SCORE | Abstention accuracy | Answerable questions wrongly abstained |",
        "|---|---|---|",
    ]
    lines += [f"| {s['threshold']:+.1f} | {s['abstention_accuracy']:.2f} | {s['false_abstains']} |" for s in ret["sweep"]]
    lines += ["", "## top_k sweep", "", "| top_k | Hit@k |", "|---|---|"]
    lines += [f"| {r['k']} | {r['hit']:.2f} |" for r in ret["top_k"]]
    lines += ["", "## Answers (full pipeline)", ""]
    if ans is None:
        lines.append("_Not run: set EVAL_PROVIDER, EVAL_SMALL_MODEL, EVAL_LARGE_MODEL and EVAL_LLM_KEY to measure answers._")
    else:
        faith = f"{ans['faithfulness']:.2f}" if ans["faithfulness"] is not None else "judge off"
        lines += [
            "| Metric | Value |",
            "|---|---|",
            f"| Citation precision | {ans['citation_precision']:.2f} |",
            f"| Abstention accuracy | {ans['abstention_accuracy']:.2f} |",
            f"| Answer accuracy (expected text present) | {ans['answer_accuracy']:.2f} |",
            f"| Faithfulness (LLM judge) | {faith} |",
            f"| Avg cost / query | ${ans['avg_cost']:.5f} |",
            f"| p50 latency | {ans['p50_latency_ms']:.0f} ms |",
            f"| Errors | {ans['errors']} |",
            "",
            "| Question | Type | Cited pages | Expected pages |",
            "|---|---|---|---|",
        ]
        for r in ans["rows"]:
            lines.append(
                f"| {r['g']['question']} | {(r['done'] or {}).get('answer_type', 'error')} | "
                f"{', '.join(str(c['page']) for c in r['cites']) or '–'} | {', '.join(map(str, r['g']['expected_pages'])) or '–'} |"
            )
    RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {RESULTS}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=settings.top_k)
    ap.add_argument("--min-score", type=float, default=None, help="override MIN_RERANK_SCORE for this run")
    ap.add_argument("--judge", action="store_true", help="enable the LLM faithfulness judge")
    args = ap.parse_args()
    if args.min_score is not None:
        settings.min_rerank_score = args.min_score

    golden = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    doc_id = ensure_indexed()
    print("Retrieval eval…")
    ret = retrieval_eval(golden, doc_id, args.top_k)
    ret["top_k"] = top_k_sweep(golden, doc_id)

    ans, cfg_line = None, "answers not evaluated"
    provider = os.environ.get("EVAL_PROVIDER")
    if provider and (os.environ.get("EVAL_LLM_KEY") or provider == "ollama"):
        cfg = LLMConfig(
            provider,
            os.environ["EVAL_SMALL_MODEL"],
            os.environ["EVAL_LARGE_MODEL"],
            os.environ.get("EVAL_LLM_KEY"),
            azure_endpoint=os.environ.get("EVAL_AZURE_ENDPOINT"),
            azure_api_version=os.environ.get("EVAL_AZURE_API_VERSION", "2024-10-21"),
        )
        cfg_line = f"provider={provider}, small={cfg.small_model}, large={cfg.large_model}"
        print("Answer eval…")
        ans = answer_eval(golden, doc_id, cfg, provider, args.judge)
    write_results(ret, ans, args.top_k, cfg_line)
    client().close()  # embedded Qdrant: close explicitly instead of at interpreter shutdown


if __name__ == "__main__":
    main()

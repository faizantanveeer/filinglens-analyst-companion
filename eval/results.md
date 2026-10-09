# FilingLens evaluation results

Generated 2026-10-09 09:52 UTC on `report.pdf` with 20 golden questions.
Config: top_k=5, MIN_RERANK_SCORE=0.0, answers not evaluated

## Retrieval (local, no LLM)

| Metric | Value |
|---|---|
| Hit@5 | 0.94 |
| MRR | 0.68 |

## Abstain-threshold sweep (top rerank score vs. answerable)

| MIN_RERANK_SCORE | Abstention accuracy | Answerable questions wrongly abstained |
|---|---|---|
| -6.0 | 0.85 | 0 |
| -4.0 | 0.85 | 0 |
| -3.0 | 0.85 | 0 |
| -2.0 | 0.90 | 0 |
| -1.0 | 0.95 | 0 |
| +0.0 | 0.95 | 0 |
| +1.0 | 0.85 | 2 |
| +2.0 | 0.85 | 2 |

## top_k sweep

| top_k | Hit@k |
|---|---|
| 3 | 0.76 |
| 5 | 0.94 |
| 8 | 1.00 |

## Answers (full pipeline)

_Not run: set EVAL_PROVIDER, EVAL_SMALL_MODEL, EVAL_LARGE_MODEL and EVAL_LLM_KEY to measure answers._

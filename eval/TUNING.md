# Tuning log

Measured on the development laptop (Windows, 8 logical CPUs, no GPU) using `eval/data/report.pdf`
(Berkshire Hathaway 2023 Annual Report, 152 pages) and `eval/golden.jsonl` (17 answerable + 3 unanswerable).
Retrieval numbers need no LLM. Small sample: treat differences of one question (about 0.06 Hit@5) as noise.

## 1. Rerank pool size (biggest latency win)

The cross-encoder dominated query latency: about 2.5 s per question, against about 0.1 s for hybrid retrieval.
Truncating chunk text didn't help: it made quality worse, and the speed gain was small until truncation became harmful.
Reranking fewer candidates did help:

| Rerank pool | Hit@5 | MRR | Avg rerank latency |
|---|---|---|---|
| 20 (original) | 0.88 | 0.65 | 2,459 ms |
| 12 | 0.88 | 0.66 | 1,330 ms |
| **10 (chosen)** | **0.94** | **0.68** | **1,009 ms** |
| 8 | 0.94 | 0.68 | 766–803 ms |
| 6 | 0.94 | 0.74 | 531 ms |

Why fewer candidates scored *better*: the first relevant chunk's position in the fused (RRF) list was
`[1, 1, 2, 4, 2, 2, 2, 1, 1, 2, 1, 1, 2, 8, 2, 1, 5]`, so it was always within rank 8. Candidates beyond that were
weak matches that only gave the cross-encoder more chances to promote a wrong chunk. A pool of 10 keeps a margin
above the worst observed rank (8), because 6 would be over-fitted to 17 questions.

After the change (`make eval`): **Hit@5 0.94, MRR 0.68, Hit@8 1.00** (were 0.88 / 0.65 / 0.94).

## 2. Abstain threshold (`MIN_RERANK_SCORE`)

| Threshold | Abstention accuracy | Answerable questions wrongly abstained |
|---|---|---|
| −2.0 | 0.90 | 0 |
| −1.0 | 0.95 | 0 |
| **0.0 (kept)** | **0.95** | **0** |
| +1.0 | 0.85 | 2 |

The one miss at 0.0 is "revenue in fiscal year 2025": the topic matches strongly (score +3.2) even though the year
doesn't exist in the report. A retrieval threshold can't catch that, so the answer step and the verifier must.

## 3. Ingestion speed (152-page PDF, 414 chunks)

| Stage | Before | After |
|---|---|---|
| Parse (pymupdf4llm) | 117 s single process | 60 s with 4 worker processes (8 workers: 67 s, no better) |
| Dense embedding (bge-small) | 91 s | unchanged (fastembed `parallel=0`: 84 s, not worth the extra processes) |
| BM25 sparse | 0.4 s | 0.4 s |
| **End to end** | **≈ 208 s** (parse, then embed) | **129 s** (parallel parse, overlapped with embedding batch by batch) |

Embedding is now the bottleneck. The next steps would be a GPU, or a smaller embedding model checked against Hit@5.

## 4. Query wording

"Plot …" / "Show me a chart of …" wording pulled the cross-encoder score of the right chunk down by about 2
(e.g. "Plot Berkshire's float by year" 2.3 → 4.2 after stripping the presentation words), enough to trip the
abstain gate on some chart questions. Retrieval now uses the query with presentation words removed
(`router.retrieval_query`); the answer step still sees the user's wording.

## 5. Other

- **Model warm-up at start-up:** the first query used to take about 3.5 s cold (model load plus ONNX init). Models now load in a
  background thread when the API starts.
- **Query embedding is cached:** the cache lookup, retrieval and memory lookup reuse one embedding of the question.
- **Not yet measured:** answer-level metrics (citation precision, end-to-end abstention, faithfulness, cost). Run
  `make eval` with `EVAL_PROVIDER` / `EVAL_LLM_KEY` set.

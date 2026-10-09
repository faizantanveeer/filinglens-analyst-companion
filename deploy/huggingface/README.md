---
title: FilingLens API
emoji: 📑
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Backend for FilingLens, grounded Q&A over annual reports
---

# FilingLens API

FastAPI backend for [FilingLens](https://github.com/faizantanveeer/filinglens-analyst-companion): hybrid retrieval (dense + BM25 → RRF),
cross-encoder reranking, grounded answers with page citations, Python arithmetic and deterministic verification.

The web app is hosted on Vercel and calls this API. Visitors bring their own LLM key; it's sent per request
and never stored. Interactive API docs: `/docs`.

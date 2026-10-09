# Deploying FilingLens (free): Vercel + Modal

```
Browser ──▶ Vercel (Next.js UI)       https://filinglens-analyst-companion.vercel.app
   └──────▶ Modal (FastAPI API)       https://<modal-workspace>--filinglens-api-api.modal.run
```

- **Why two hosts:** the API runs local embedding and reranking models, an on-disk vector index, background ingestion and SQLite. That needs ~2–3 GB of RAM and a long-lived process, which Vercel's serverless functions can't host. Free "always-on" tiers elsewhere give only 256–512 MB. Modal runs the container on demand, and its free plan includes monthly credits.
- **Why there are no CORS problems:** the browser calls the API directly. The API only accepts your Vercel production origin plus preview URLs of this project (a regex), set when the image is built. Large uploads and long streaming answers don't pass through Vercel, so its body-size and duration limits don't apply.

## 1. Backend: Modal (≈10 min, mostly the first image build)

1. Create a free account at modal.com (sign in with GitHub).
2. Log in once on your machine. It opens the browser and stores a token in `~/.modal.toml`:
   ```bash
   .venv/Scripts/modal setup
   ```
3. Deploy. The defaults target `https://filinglens-analyst-companion.vercel.app`; override them with the
   `FILINGLENS_FRONTEND_ORIGIN` / `FILINGLENS_ORIGIN_REGEX` / `FILINGLENS_SEC_USER_AGENT` env vars if needed:
   ```bash
   .venv/Scripts/modal deploy deploy/modal_app.py
   ```
   The first build installs dependencies, bakes in the models and indexes the sample report (~5–10 min).
   Later deploys reuse cached layers. The command prints the URL; check `<url>/health` returns `{"status":"ok"}`.

How it runs:
- **One container** (`max_containers=1`), because the embedded index and SQLite are single-process. It serves up to 32 requests at once.
- **The Berkshire Hathaway 2023 report is pre-indexed and protected.** Uploads are capped at 20 MB.
- **It scales to zero after 15 idle minutes.** The next visit wakes it in about 10–30 s, and the UI shows "Waking API…". Visitor uploads and chats live on the container disk and reset when it scales down.

## 2. Frontend: Vercel (≈3 min)

1. At vercel.com → **Add New… → Project → Import** `faizantanveeer/filinglens-analyst-companion` (GitHub is connected).
2. Configure:
   - **Project Name:** `filinglens-analyst-companion` (it must match the origin the API allows)
   - **Root Directory:** `frontend` ← important
   - **Framework Preset:** Next.js (auto-detected)
   - **Environment Variable:** `NEXT_PUBLIC_API_URL` = the Modal URL from step 1.3
3. **Deploy.** Production builds from `main`; pushes to `dev` get preview URLs, which the API accepts.

If Vercel gives a different domain (name taken) or you add a custom domain, redeploy the API with
`FILINGLENS_FRONTEND_ORIGIN=https://<your-domain>` (and a matching `FILINGLENS_ORIGIN_REGEX`).

## 3. Check it works

- Open the Vercel URL. The header badge turns **API online** (or shows "Waking API…" first).
- **Settings:** add your model key (it stays in the browser tab), then **Test connection**.
- **Chat:** try the Executive briefing starter. Citations open the real page with highlights.
- **Documents:** import a filing by ticker (e.g. `AAPL`, 10-K).

## Branch workflow

- `dev`: day-to-day work; every push gets a Vercel preview URL.
- `main`: production; merge `dev` → `main` to update the live site.
- **Backend changes:** `modal deploy deploy/modal_app.py` from the branch you mean to release.

## Alternative: Hugging Face Spaces (paid)

`deploy/huggingface/` and `deploy/push_space.py` package the same API as a Docker Space; the image is built and tested.
Hugging Face now requires a PRO subscription for Docker Spaces on CPU (`402 Payment Required` for free accounts), so
this route is kept only as a paid option.

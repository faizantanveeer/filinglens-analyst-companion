# Deploying FilingLens (free): Vercel + Hugging Face Spaces

```
Browser ──▶ Vercel (Next.js UI)            https://<vercel-project>.vercel.app
   └──────▶ Hugging Face Space (FastAPI)   https://<hf-user>-filinglens-api.hf.space
```

- **Why two hosts:** the API runs local embedding and reranking models, an on-disk vector index, background ingestion and SQLite. That's a ~1.4 GB container with a long-running process, which Vercel's serverless functions can't host (size limits, short timeouts, no disk). A Hugging Face Space (free CPU tier: 2 vCPU, 16 GB RAM, Docker) can.
- **Why there are no CORS problems:** the browser calls the Space directly. The Space only accepts your Vercel production origin (`FRONTEND_ORIGIN`) plus preview URLs of *this* project (`FRONTEND_ORIGIN_REGEX`). Large uploads and long streaming answers don't pass through Vercel, so its request-size and duration limits don't apply.

## 1. Backend: Hugging Face Space (≈15 min, mostly build time)

1. Create a free account at huggingface.co. Then go to **Settings → Access Tokens → New token → type "Write"**.
2. Log in once on your machine. The token is stored by the HF client; never paste it into code or chat:
   ```bash
   .venv/Scripts/hf auth login          # Windows (Linux/macOS: .venv/bin/hf auth login)
   ```
3. Push the API (replace `<hf-user>`; the Vercel URL is what you'll name the project in step 2.2):
   ```bash
   .venv/Scripts/python deploy/push_space.py \
     --space <hf-user>/filinglens-api \
     --frontend-origin https://filinglens-analyst-companion.vercel.app \
     --preview-regex "^https://filinglens-analyst-companion(-[a-z0-9-]+)?\.vercel\.app$" \
     --sec-user-agent "FilingLens your.email@example.com"
   ```
4. Watch the build at `https://huggingface.co/spaces/<hf-user>/filinglens-api`. It installs dependencies, bakes the models in and indexes the sample report. When it shows **Running**, check `https://<hf-user>-filinglens-api.hf.space/health` returns `{"status":"ok"}`.

The Space ships with the Berkshire Hathaway 2023 report pre-indexed and **protected**: visitors can't delete it.
Uploads are capped at 20 MB. Free Spaces have no persistent disk, so visitor uploads and chats reset when the Space
restarts, and it sleeps after ~48 h without traffic. The first visit then takes 1–2 min, and the UI shows "Waking API…".

## 2. Frontend: Vercel (≈3 min)

1. At vercel.com → **Add New… → Project → Import** `faizantanveeer/filinglens-analyst-companion` (GitHub is already connected).
2. Configure:
   - **Project Name:** `filinglens-analyst-companion` (this gives the URL used in step 1.3)
   - **Root Directory:** `frontend` ← important
   - **Framework Preset:** Next.js (auto-detected)
   - **Environment Variable:** `NEXT_PUBLIC_API_URL` = `https://<hf-user>-filinglens-api.hf.space`
3. **Deploy.** Production deploys from `main`; pushes to `dev` get preview URLs, which the backend accepts via the regex above.

If you choose a different project name or add a custom domain, re-run step 1.3 with the new origin. It only updates
the Space variables; the Space restarts on its own.

## 3. Check it works

- Open the Vercel URL. The header badge should turn **API online** (or show "Waking API…" first).
- **Settings:** paste your model key (it stays in the browser tab), then **Test connection**.
- **Chat:** try the Executive briefing starter. Citations should open the real page with highlights.
- **Documents:** import a filing by ticker (e.g. `AAPL`, 10-K).

## Branch workflow

- `dev`: day-to-day work. Every push gets its own Vercel preview URL.
- `main`: production. Merge `dev` → `main` (pull request on GitHub) to update the live site.
- **Backend changes:** re-run `deploy/push_space.py`. The Space rebuilds from your local files, so push from the branch you mean to release.

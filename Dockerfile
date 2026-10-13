# syntax=docker/dockerfile:1
# FinCite in local mode (SQLite, embedded Qdrant, local models), as two images from one file:
#   docker compose up --build                     # both, via docker-compose.yml
#   docker build --target api -t fincite-api .    # API only (port 8000)
#   docker build --target ui  -t fincite-ui  .    # UI only (port 3000)
# Hosting is on Vercel (docs/DEPLOY.md); this is for running the whole app without start.command.

# ---------- API ----------
FROM python:3.13-slim AS api
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FASTEMBED_CACHE_PATH=/models DATA_DIR=/data

COPY requirements.txt requirements-local.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-local.txt

# Bake the local models in their own layer (it only needs the config), so the first question doesn't
# wait for downloads and code changes don't download them again.
COPY backend/__init__.py backend/
COPY backend/app/__init__.py backend/app/config.py backend/app/embeddings.py backend/app/
RUN python -c "from backend.app.embeddings import dense_model, sparse_model, rerank_model; dense_model(); sparse_model(); rerank_model()"

COPY backend ./backend
RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown -R app /data /models
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------- UI ----------
FROM node:22-alpine AS ui-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY frontend ./
# NEXT_PUBLIC_* values are inlined at build time, so the API URL is a build argument.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS ui
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=ui-build --chown=node /app/.next/standalone ./
COPY --from=ui-build --chown=node /app/.next/static ./.next/static
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:3000 >/dev/null || exit 1
CMD ["node", "server.js"]

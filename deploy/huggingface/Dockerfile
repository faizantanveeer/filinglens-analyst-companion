# FilingLens API on a Hugging Face Space (Docker, free CPU tier).
# The frontend is deployed separately on Vercel and calls this API directly (CORS is set via Space variables).
FROM python:3.13-slim

# Spaces run containers as uid 1000; build as that user so runtime can write to the baked-in data dir.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FASTEMBED_CACHE_PATH=/home/user/models \
    DATA_DIR=/home/user/data \
    MAX_UPLOAD_MB=20 \
    PARSE_WORKERS=2
WORKDIR /home/user/app

COPY --chown=user requirements.txt requirements-local.txt ./
RUN pip install --no-cache-dir --user -r requirements-local.txt

COPY --chown=user backend ./backend

# Bake the local models into the image (no download on first request)...
RUN python -c "from backend.app.embeddings import dense_model, sparse_model, rerank_model; dense_model(); sparse_model(); rerank_model()"
# ...and index the sample report at build time: free Spaces have no persistent disk, so a fresh
# container must start with a ready document instead of re-indexing for minutes after each restart.
RUN python -m backend.app.seed

EXPOSE 7860
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "7860"]

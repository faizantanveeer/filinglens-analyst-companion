"""FilingLens API on Modal (serverless containers; the free plan includes monthly credits).

    .venv/Scripts/modal setup        # once: browser login, stores a token in ~/.modal.toml
    # Optional overrides (defaults match docs/DEPLOY.md):
    #   FILINGLENS_FRONTEND_ORIGIN=https://<project>.vercel.app
    #   FILINGLENS_ORIGIN_REGEX=^https://<project>(-[a-z0-9-]+)?\\.vercel\\.app$
    #   FILINGLENS_SEC_USER_AGENT="FilingLens you@example.com"
    .venv/Scripts/modal deploy deploy/modal_app.py

Prints the public URL (https://<workspace>--filinglens-api-api.modal.run); set it as NEXT_PUBLIC_API_URL in Vercel.

Design notes:
- One container (max_containers=1): the embedded Qdrant index and SQLite are single-process, so every
  request must reach the same container. That container serves many requests concurrently.
- The image bakes in the models and the indexed sample report, so a cold start is just "load models"
  (~10-30 s), not "re-index for minutes".
- It scales to zero after 15 idle minutes to save credits. Visitor uploads and chats live on the container
  disk and reset when it scales down; the protected sample report is always there.
"""

import os
import sys
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent

FRONTEND_ORIGIN = os.environ.get("FILINGLENS_FRONTEND_ORIGIN", "https://filinglens-analyst-companion.vercel.app")
ORIGIN_REGEX = os.environ.get("FILINGLENS_ORIGIN_REGEX", r"^https://filinglens-analyst-companion(-[a-z0-9-]+)?\.vercel\.app$")
SEC_USER_AGENT = os.environ.get("FILINGLENS_SEC_USER_AGENT", "FilingLens 134828035+faizantanveeer@users.noreply.github.com")

image = (
    modal.Image.debian_slim(python_version="3.13")
    .pip_install_from_requirements(str(ROOT / "requirements.txt"))
    .pip_install("uvicorn[standard]==0.54.0", "litellm==1.104.2", "fastembed==0.9.0")  # local-mode extras
    .env(
        {
            "FASTEMBED_CACHE_PATH": "/models",
            "DATA_DIR": "/data",
            "MAX_UPLOAD_MB": "20",
            "PARSE_WORKERS": "2",
            "FRONTEND_ORIGIN": FRONTEND_ORIGIN,
            "FRONTEND_ORIGIN_REGEX": ORIGIN_REGEX,
            "SEC_USER_AGENT": SEC_USER_AGENT,
            "PYTHONUNBUFFERED": "1",
        }
    )
    .add_local_dir(str(ROOT / "backend"), "/srv/backend", copy=True, ignore=["**/__pycache__", "**/*.pyc"])
    # Bake models and the indexed, protected sample into the image (build-time, not per cold start).
    .run_commands(
        "cd /srv && python -c 'from backend.app.embeddings import dense_model, sparse_model, rerank_model; "
        "dense_model(); sparse_model(); rerank_model()'",
        "cd /srv && python -m backend.app.seed",
    )
)

app = modal.App("filinglens-api", image=image)


@app.function(
    cpu=2.0,
    memory=3072,  # MiB: models + parsing workers + headroom
    timeout=900,  # long Deep-research answers and large ingests
    scaledown_window=15 * 60,
    min_containers=0,
    max_containers=1,
)
@modal.concurrent(max_inputs=32)
@modal.asgi_app()
def api():
    sys.path.insert(0, "/srv")
    os.chdir("/srv")
    from backend.app.main import app as fastapi_app

    return fastapi_app

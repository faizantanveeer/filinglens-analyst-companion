"""Vercel entry point for the FilingLens API (cloud mode).

Vercel runs this as a Python serverless function. Every URL is rewritten to /api/index (see
vercel.json) with the original path in ?__path=..., and RestorePath puts it back before routing.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Serverless defaults: hosted services, writable scratch space only under /tmp, and no process
# pools (Vercel's runtime has no /dev/shm), so parsing runs in-process.
os.environ.setdefault("DEPLOY_MODE", "cloud")
os.environ.setdefault("DATA_DIR", "/tmp/filinglens")
os.environ.setdefault("PARSE_WORKERS", "1")

from backend.app.main import app  # noqa: E402
from backend.app.serverless import RestorePath  # noqa: E402

app.add_middleware(RestorePath)

"""Create/update the Hugging Face Space that hosts the FilingLens API.

    hf auth login                          # once; paste a *write* token from huggingface.co/settings/tokens
    python deploy/push_space.py --space <hf-username>/filinglens-api \\
        --frontend-origin https://<your-project>.vercel.app \\
        --sec-user-agent "FilingLens your.email@example.com"

Uploads only what the API needs (backend/, requirements.txt, Dockerfile, Space README), then sets the
Space variables for CORS and SEC EDGAR. The Space rebuilds automatically after each push.
"""

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent


def space_url(repo_id: str) -> str:
    owner, name = repo_id.split("/")
    return f"https://{re.sub(r'[^a-z0-9]+', '-', owner.lower())}-{re.sub(r'[^a-z0-9]+', '-', name.lower())}.hf.space"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", required=True, help="<hf-username>/<space-name>, e.g. jane/filinglens-api")
    ap.add_argument("--frontend-origin", required=True, help="Production URL of the Vercel app, e.g. https://filinglens.vercel.app")
    ap.add_argument("--preview-regex", default="", help="Optional regex for Vercel preview URLs of this project")
    ap.add_argument("--sec-user-agent", default="", help='SEC requires contact details, e.g. "FilingLens you@example.com"')
    args = ap.parse_args()

    origin = args.frontend_origin.rstrip("/")
    if not re.match(r"^https://[a-z0-9.-]+$", origin):
        sys.exit("--frontend-origin must look like https://name.vercel.app (no path)")
    api = HfApi()
    print(f"Logged in to Hugging Face as {api.whoami()['name']}")

    api.create_repo(args.space, repo_type="space", space_sdk="docker", exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        shutil.copytree(ROOT / "backend", stage / "backend", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy(ROOT / "requirements.txt", stage / "requirements.txt")
        shutil.copy(ROOT / "requirements-local.txt", stage / "requirements-local.txt")
        shutil.copy(ROOT / "deploy" / "huggingface" / "Dockerfile", stage / "Dockerfile")
        shutil.copy(ROOT / "deploy" / "huggingface" / "README.md", stage / "README.md")
        api.upload_folder(
            folder_path=stage,
            repo_id=args.space,
            repo_type="space",
            commit_message="Deploy FilingLens API",
            delete_patterns=["backend/**"],  # remove files deleted locally
        )

    # CORS: the Vercel production origin, plus optional preview deployments of this project only.
    api.add_space_variable(args.space, "FRONTEND_ORIGIN", origin)
    if args.preview_regex:
        api.add_space_variable(args.space, "FRONTEND_ORIGIN_REGEX", args.preview_regex)
    if args.sec_user_agent:
        api.add_space_variable(args.space, "SEC_USER_AGENT", args.sec_user_agent)

    url = space_url(args.space)
    print(f"\nPushed. The Space builds now (about 10-15 min the first time: dependencies, models, sample index).")
    print(f"  Build logs:  https://huggingface.co/spaces/{args.space}")
    print(f"  API URL:     {url}   (health check: {url}/health)")
    print(f"\nIn Vercel, set NEXT_PUBLIC_API_URL={url} and redeploy.")


if __name__ == "__main__":
    main()

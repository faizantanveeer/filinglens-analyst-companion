# Works with GNU make on macOS/Linux and on Windows (Git Bash + make).
ifeq ($(OS),Windows_NT)
  PY := .venv/Scripts/python
  BASE_PY ?= python
else
  PY := .venv/bin/python
  # macOS's own python3 is 3.9; prefer a newer one (e.g. `brew install python@3.13`). Override with BASE_PY=...
  BASE_PY ?= $(shell for p in python3.13 python3.12 python3.11 python3; do command -v $$p >/dev/null 2>&1 && echo $$p && break; done)
endif

API_PORT ?= 8000

.PHONY: install api ui test eval up

install:
	$(BASE_PY) -m venv .venv
	$(PY) -m pip install -r requirements-local.txt
	cd frontend && npm ci

api:
	$(PY) -m uvicorn backend.app.main:app --reload --reload-dir backend --port $(API_PORT)

ui:
	cd frontend && npm run dev

test:
	$(PY) -m pytest -q

eval:
	$(PY) eval/run_eval.py

up:
	docker compose up --build

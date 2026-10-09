# Works with GNU make on macOS/Linux and on Windows (Git Bash + make).
ifeq ($(OS),Windows_NT)
  PY := .venv/Scripts/python
else
  PY := .venv/bin/python
endif

API_PORT ?= 8000

.PHONY: install api ui test eval up

install:
	python -m venv .venv
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

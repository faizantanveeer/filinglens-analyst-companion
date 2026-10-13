#!/bin/bash
# FinCite on macOS: double-click in Finder (or run ./start.command). Installs what's missing,
# starts the API and the UI, waits until both answer, then opens the browser.
# Stop with Ctrl+C (or close the window): both servers stop with it.

cd "$(dirname "$0")" || exit 1

# Finder starts .command files without your shell profile, so Homebrew isn't on PATH yet.
for brew in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$brew" ] && eval "$("$brew" shellenv)" && break
done

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

fail() {
    echo
    echo "Setup failed: $1"
    read -r -p "Press Return to close."
    exit 1
}

# ---- Python 3.11+ (macOS's own python3 is 3.9, too old for this project) ----
python_ok() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; }

find_python() {
    for p in python3.13 python3.12 python3.11 python3; do
        command -v "$p" >/dev/null && python_ok "$p" && { command -v "$p"; return; }
    done
}

if [ -x .venv/bin/python ] && ! python_ok .venv/bin/python; then
    echo "The existing .venv uses an old Python; recreating it..."
    rm -rf .venv
fi

if [ ! -x .venv/bin/python ]; then
    PY=$(find_python)
    if [ -z "$PY" ] && command -v brew >/dev/null; then
        echo "Installing Python 3.13 with Homebrew..."
        brew install python@3.13 || fail "could not install Python 3.13."
        PY=$(find_python)
    fi
    [ -n "$PY" ] || fail "Python 3.11+ is required. Install Homebrew (https://brew.sh), then run: brew install python@3.13"
    echo "Creating Python virtual environment with $("$PY" --version)..."
    "$PY" -m venv .venv || fail "could not create .venv."
fi

# Reinstall when the requirements change, or when an earlier install didn't finish.
STAMP=.venv/.installed
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ] || [ requirements-local.txt -nt "$STAMP" ]; then
    echo "Installing Python dependencies (the first time takes a few minutes)..."
    .venv/bin/python -m pip install --upgrade pip >/dev/null &&
        .venv/bin/python -m pip install -r requirements-local.txt || fail "pip install failed (see above)."
    touch "$STAMP"
fi

# ---- Node.js 20+ ----
if ! command -v npm >/dev/null; then
    if command -v brew >/dev/null; then
        echo "Installing Node.js with Homebrew..."
        brew install node || fail "could not install Node.js."
    else
        fail "Node.js 20+ is required. Install it from https://nodejs.org or with Homebrew: brew install node"
    fi
fi

NODE_STAMP=frontend/node_modules/.installed
if [ ! -f "$NODE_STAMP" ] || [ frontend/package-lock.json -nt "$NODE_STAMP" ]; then
    echo "Installing frontend dependencies..."
    (cd frontend && npm ci) || fail "npm ci failed (see above)."
    touch "$NODE_STAMP"
fi

# ---- ports: the first free one from 8000 (API) and 3000 (UI) ----
port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1; }
free_port() {
    local p=$1
    while port_busy "$p"; do p=$((p + 1)); done
    echo "$p"
}
API_PORT=$(free_port 8000)
UI_PORT=$(free_port 3000)
# 127.0.0.1, not localhost: uvicorn listens on IPv4 only, and "localhost" may try IPv6 first.
API_URL="http://127.0.0.1:$API_PORT"
UI_URL="http://localhost:$UI_PORT"

# ---- start both servers ----
API_PID=""
UI_PID=""

# Stop a process and everything it started (npm runs next, which runs its own workers).
kill_tree() {
    local pid=$1 child
    [ -n "$pid" ] || return
    for child in $(pgrep -P "$pid"); do kill_tree "$child"; done
    kill "$pid" 2>/dev/null
}

cleanup() {
    local code=$?
    trap - INT TERM HUP EXIT
    echo
    echo "Stopping FinCite..."
    kill_tree "$UI_PID"
    kill_tree "$API_PID"
    wait 2>/dev/null
    exit "$code"
}
trap cleanup INT TERM HUP EXIT

echo "Starting the API on $API_URL (log: $LOG_DIR/backend.log)"
# The API only accepts browser calls from the UI's origin (CORS), so tell it which port the UI got.
FRONTEND_ORIGIN="$UI_URL,http://127.0.0.1:$UI_PORT" \
    .venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port "$API_PORT" >"$LOG_DIR/backend.log" 2>&1 &
API_PID=$!

echo "Starting the UI on $UI_URL (log: $LOG_DIR/frontend.log)"
# Process env overrides frontend/.env.local, so the UI always points at the API started above.
(cd frontend && NEXT_PUBLIC_API_URL="$API_URL" exec npm run dev -- --port "$UI_PORT") >"$LOG_DIR/frontend.log" 2>&1 &
UI_PID=$!

# ---- wait until each server answers (up to 120 s each) ----
wait_for() {
    local name=$1 url=$2 pid=$3 log=$4
    printf "Waiting for the %s " "$name"
    for _ in $(seq 1 120); do
        if curl -s -o /dev/null -m 2 "$url"; then
            echo " ready"
            return 0
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            break  # it exited: no point waiting
        fi
        printf "."
        sleep 1
    done
    echo
    echo "The $name did not start. Last lines of $log:"
    tail -n 20 "$log"
    read -r -p "Press Return to close."
    exit 1
}

wait_for "API" "$API_URL/health" "$API_PID" "$LOG_DIR/backend.log"
wait_for "UI" "$UI_URL" "$UI_PID" "$LOG_DIR/frontend.log"

open "$UI_URL"
echo
echo "FinCite is running at $UI_URL (API: $API_URL)."
echo "Press Ctrl+C or close this window to stop both servers."
wait

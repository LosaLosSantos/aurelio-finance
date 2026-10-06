#!/usr/bin/env bash
# Aurelio: one command, one URL, on macOS and Linux (start.ps1 does the same on
# Windows).
#
# Builds the frontend into frontend/dist (which FastAPI then serves itself),
# starts the backend, and opens the browser. No second terminal, no Node left
# running, no CORS: everything lives on http://localhost:8000.
#
#   ./start.sh               your own data, in backend/data.db
#   ./start.sh --demo        an invented household in backend/demo.db, built on
#                            first use; your data.db is never opened
#   ./start.sh --no-browser  start it without opening a browser
#
# For day-to-day development prefer two terminals instead: `npm run dev` in
# frontend/ gives hot reload and proxies /api here.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
port=8000
demo=0
browser=1
for arg in "$@"; do
  case "$arg" in
    --demo) demo=1 ;;
    --no-browser) browser=0 ;;
    -h|--help) sed -n '9,12p' "$0" | cut -c3-; exit 0 ;;
    *) echo "Unknown option: $arg (the options are --demo and --no-browser)" >&2; exit 2 ;;
  esac
done

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Aurelio needs $1, and this machine does not have it. $2" >&2
    exit 1
  fi
}
need npm "Install Node.js 22 or later from https://nodejs.org (npm comes with it)."
need uv "Install uv from https://docs.astral.sh/uv/ (it brings the Python it needs)."

echo "Building the frontend..."
cd "$root/frontend"
[ -d node_modules ] || npm install
npm run build

cd "$root/backend"
if [ "$demo" = 1 ]; then
  uv run python -m app.demo --if-missing
  # Relative to backend/, where the server runs: the same file the line above
  # built, written in a way every platform's Python reads alike.
  export DATABASE_URL="sqlite:///demo.db"
  echo "Demo data: backend/demo.db. Your own data.db is not opened."
fi

echo "Starting Aurelio on http://localhost:$port"
if [ "$browser" = 1 ]; then
  # Give uvicorn a moment to bind before the browser asks for the page.
  (
    sleep 3
    if [ "$(uname -s)" = Darwin ] && command -v open >/dev/null 2>&1; then
      open "http://localhost:$port"
    elif command -v xdg-open >/dev/null 2>&1; then
      xdg-open "http://localhost:$port" >/dev/null 2>&1 || true
    else
      echo "Open http://localhost:$port in your browser."
    fi
  ) &
fi
# No line per request: this console is where problems show up, and a request
# log would bury them. Startup lines and tracebacks still print.
exec uv run uvicorn app.main:app --port "$port" --no-access-log

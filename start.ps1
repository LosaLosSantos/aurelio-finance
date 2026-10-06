# Aurelio — one command, one URL.
#
# Builds the frontend into frontend/dist (which FastAPI then serves itself),
# starts the backend, and opens the browser. No second terminal, no Node left
# running, no CORS: everything lives on http://localhost:8000.
#
#   ./start.ps1             your own data, in backend/data.db
#   ./start.ps1 -Demo       an invented household in backend/demo.db, built on
#                           first use; your data.db is never opened
#   ./start.ps1 -NoBrowser  start it without opening a browser
#
# For day-to-day development prefer two terminals instead — `npm run dev` gives
# hot reload and proxies /api here. start.sh does the same on macOS and Linux.

param([switch]$Demo, [switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$port = 8000

Write-Host "Building the frontend..." -ForegroundColor Cyan
Push-Location (Join-Path $root "frontend")
if (-not (Test-Path "node_modules")) { npm install }
npm run build
Pop-Location

Push-Location (Join-Path $root "backend")
# $env: belongs to this whole PowerShell window, not to this script: it is put
# back on the way out, or the next plain start in the same window would open
# the demo instead of your data.
$previous = $env:DATABASE_URL
try {
  if ($Demo) {
    uv run python -m app.demo --if-missing
    if ($LASTEXITCODE -ne 0) { throw "The demo database could not be built." }
    # Relative to backend/, where the server runs: the file the line above built.
    $env:DATABASE_URL = "sqlite:///demo.db"
    Write-Host "Demo data: backend/demo.db. Your own data.db is not opened." -ForegroundColor Yellow
  }
  Write-Host "Starting Aurelio on http://localhost:$port" -ForegroundColor Cyan
  if (-not $NoBrowser) {
    # Give uvicorn a moment to bind before the browser asks for the page.
    Start-Job -ScriptBlock {
      Start-Sleep -Seconds 3
      Start-Process "http://localhost:$using:port"
    } | Out-Null
  }
  # No line per request: this console is where problems show up, and a request
  # log would bury them. Startup lines and tracebacks still print.
  uv run uvicorn app.main:app --port $port --no-access-log
}
finally {
  $env:DATABASE_URL = $previous
  Pop-Location
}

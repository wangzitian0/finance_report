#!/usr/bin/env bash
# Wrapper for dev servers with proper cleanup on Ctrl+C
# Usage: scripts/dev_backend.sh
#
# Resources managed:
# - uvicorn dev server
# - Development database container (optional, via COMPOSE_FILE)
#
# Lifecycle: Starts with script, stops on Ctrl+C (SIGINT/SIGTERM)

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="${COMPOSE_FILE:-$repo_root/docker-compose.ci.yml}"

# Detect compose command
compose_cmd=()
runtime_cmd=()

if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
  compose_cmd=(podman compose)
  runtime_cmd=(podman)
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  compose_cmd=(docker compose)
  runtime_cmd=(docker)
fi

DB_STARTED=false

cleanup() {
  echo ""
  echo "🧹 Cleaning up dev resources..."
  
  # Kill the uvicorn process if running
  if [ -n "${UVICORN_PID:-}" ] && kill -0 "$UVICORN_PID" 2>/dev/null; then
    kill "$UVICORN_PID" 2>/dev/null || true
    echo "  ✓ Stopped uvicorn"
  fi
  
  # Stop database if we started it
  if [ "$DB_STARTED" = true ] && [ ${#compose_cmd[@]} -gt 0 ]; then
    "${compose_cmd[@]}" -f "$compose_file" down postgres 2>/dev/null || true
    echo "  ✓ Stopped dev database"
  fi
  
  echo "✅ Cleanup complete"
}

trap cleanup EXIT INT TERM

# Start database if compose is available
if [ ${#compose_cmd[@]} -gt 0 ]; then
  echo "🐘 Starting development database..."
  "${compose_cmd[@]}" -f "$compose_file" up -d postgres
  DB_STARTED=true
  
  # Wait for database to be ready
  for _ in {1..30}; do
    if "${compose_cmd[@]}" -f "$compose_file" exec -T postgres pg_isready -U postgres >/dev/null 2>&1; then
      echo "  ✓ Database ready"
      break
    fi
    sleep 1
  done
fi

# Set environment variables
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report}"

echo "🚀 Starting FastAPI dev server on http://localhost:8000"
echo "   Press Ctrl+C to stop"
echo ""

cd "$repo_root/apps/backend"
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

# Wait for the server process
wait $UVICORN_PID

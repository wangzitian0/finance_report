#!/usr/bin/env bash
# Wrapper for frontend dev server with proper cleanup on Ctrl+C
# Usage: scripts/dev_frontend.sh
#
# Resources managed:
# - Next.js dev server
# - Orphan node processes
#
# Lifecycle: Starts with script, stops on Ctrl+C (SIGINT/SIGTERM)

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cleanup() {
  echo ""
  echo "🧹 Cleaning up frontend resources..."
  
  # Kill the next.js process if running
  if [ -n "${NEXT_PID:-}" ] && kill -0 "$NEXT_PID" 2>/dev/null; then
    kill "$NEXT_PID" 2>/dev/null || true
    echo "  ✓ Stopped Next.js dev server"
  fi
  
  # Clean up any orphan next processes on our port
  lsof -ti :3000 2>/dev/null | xargs -r kill 2>/dev/null || true
  
  echo "✅ Cleanup complete"
}

trap cleanup EXIT INT TERM

echo "🚀 Starting Next.js dev server on http://localhost:3000"
echo "   Press Ctrl+C to stop"
echo ""

cd "$repo_root/apps/frontend"
npm run dev &
NEXT_PID=$!

# Wait for the server process
wait $NEXT_PID

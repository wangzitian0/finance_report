#!/usr/bin/env bash
# scripts/cleanup_dev_resources.sh
# 
# Use this script to clean up development resources (containers, processes, locks)
# when "make clean" is not enough or when CI/Tests are stuck.

set -u

echo "🧹 Starting cleanup of Finance Report dev resources..."

# 1. Clean up containers
SERVICES=("finance-report-db" "finance-report-redis" "finance-report-minio" "finance-report-minio-init")
echo "🐳 Checking for lingering containers (${SERVICES[*]})..."

if command -v docker >/dev/null 2>&1; then
    RUNTIME="docker"
elif command -v podman >/dev/null 2>&1; then
    RUNTIME="podman"
else
    echo "⚠️  No docker/podman found. Skipping container cleanup."
    RUNTIME=""
fi

if [ -n "$RUNTIME" ]; then
    for SERVICE in "${SERVICES[@]}"; do
        # Find all containers matching the name prefix (handling ENV_SUFFIX)
        CONTAINERS=$($RUNTIME ps -a --filter "name=${SERVICE}" --format "{{.ID}}")
        if [ -n "$CONTAINERS" ]; then
            echo "   Found containers for $SERVICE. Removing..."
            echo "$CONTAINERS" | xargs $RUNTIME rm -f
        fi
    done
    echo "   ✅ Containers cleaned."
    
    # Clean up volumes (optional, maybe user wants to keep data? But this is for leaks)
    if [[ "${1:-}" == "--all" ]]; then
        echo "   Removing volumes..."
        $RUNTIME volume ls --format "{{.Name}}" | grep "finance-report" | xargs $RUNTIME volume rm 2>/dev/null || true
    fi
fi

# 2. Clean up processes
echo "🔪 Checking for lingering Python/Node processes..."
# Find processes related to this project's backend/frontend
# We use pgrep with full command line matching

# Backend (uvicorn serving src.main:app)
PIDS=$(pgrep -f "uvicorn src.main:app" || true)
if [ -n "$PIDS" ]; then
    echo "   Killing backend servers: $PIDS"
    kill $PIDS 2>/dev/null || true
fi

# Tests (pytest running in this repo)
# Be careful not to kill other pytests
# We look for pytest processes that have 'finance_report' in their CWD or args
# Since we can't easily check CWD with pgrep, we rely on user running this in the root.
PIDS=$(pgrep -f "pytest" | grep -v $$ || true)
if [ -n "$PIDS" ]; then
    echo "   ⚠️  Found pytest processes: $PIDS"
    echo "       Only kill these if you are sure they are stuck."
    # We don't auto-kill generic pytest to be safe, unless forceful
    if [[ "${1:-}" == "--force" ]]; then
        kill $PIDS 2>/dev/null || true
        echo "       Killed."
    fi
fi

# 3. Clean up lock files
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/finance_report"
if [ -d "$CACHE_DIR" ]; then
    echo "🔒 Cleaning up lock files in $CACHE_DIR..."
    rm -rf "$CACHE_DIR"
    echo "   ✅ Removed lock files."
fi

echo "✨ Cleanup complete. Try running your tests/CI again."

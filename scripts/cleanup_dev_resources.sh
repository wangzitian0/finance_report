#!/usr/bin/env bash
# scripts/cleanup_dev_resources.sh
# 
# Use this script to clean up development resources (containers, processes, locks, data)
# when "make clean" is not enough or when CI/Tests are stuck.
#
# Usage:
#   ./scripts/cleanup_dev_resources.sh           # Clean containers and locks only
#   ./scripts/cleanup_dev_resources.sh --all     # Also clean volumes (data loss!)
#   ./scripts/cleanup_dev_resources.sh --force   # Force kill processes

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
        CONTAINERS=$($RUNTIME ps -a --filter "name=${SERVICE}" --format "{{.ID}}")
        if [ -n "$CONTAINERS" ]; then
            echo "   Found containers for $SERVICE. Removing..."
            echo "$CONTAINERS" | xargs $RUNTIME rm -f
        fi
    done
    echo "   ✅ Containers cleaned."
    
    if [[ "${1:-}" == "--all" ]]; then
        echo "   🗑️  Removing volumes (THIS WILL DELETE ALL DATA)..."
        $RUNTIME volume ls --format "{{.Name}}" | grep "finance.*report" | xargs -r $RUNTIME volume rm 2>/dev/null || true
        echo "   ✅ Volumes removed."
        
        echo "   🗑️  Cleaning MinIO data via mc (MinIO Client)..."
        MINIO_RUNNING=$($RUNTIME ps -q -f "name=finance-report-minio" 2>/dev/null || true)
        if [ -n "$MINIO_RUNNING" ]; then
            $RUNTIME exec finance-report-minio sh -c '
                mc alias set local http://localhost:9000 ${MINIO_ROOT_USER} ${MINIO_ROOT_PASSWORD} 2>/dev/null || true
                mc rm --recursive --force local/statements* 2>/dev/null || echo "No MinIO buckets to clean"
            ' 2>/dev/null || echo "   ⚠️  MinIO cleanup skipped (container not accessible)"
            echo "   ✅ MinIO data cleaned."
        else
            echo "   ℹ️  MinIO not running, skipping data cleanup."
        fi
    fi
fi

# 2. Clean up processes
echo "🔪 Checking for lingering Python/Node processes..."

PIDS=$(pgrep -f "uvicorn src.main:app" || true)
if [ -n "$PIDS" ]; then
    echo "   Killing backend servers: $PIDS"
    kill $PIDS 2>/dev/null || true
fi

PIDS=$(pgrep -f "pytest" | grep -v $$ || true)
if [ -n "$PIDS" ]; then
    echo "   ⚠️  Found pytest processes: $PIDS"
    echo "       Only kill these if you are sure they are stuck."
    if [[ "${1:-}" == "--force" ]]; then
        kill $PIDS 2>/dev/null || true
        echo "       Killed."
    fi
fi

# 3. Clean up leaked CI/Test containers/networks (finance-report-internal-*)
echo "🕵️  Checking for leaked CI/Test resources (finance-report-internal-*)..."

LEAKED_CONTAINERS=$($RUNTIME ps -a --format "{{.Names}}" | grep "finance-report-internal" || true)
if [ -n "$LEAKED_CONTAINERS" ]; then
    echo "   Found leaked containers:"
    echo "$LEAKED_CONTAINERS" | sed 's/^/   - /'
    if [[ "${1:-}" == "--all" || "${1:-}" == "--force" ]]; then
       echo "$LEAKED_CONTAINERS" | xargs $RUNTIME rm -f
       echo "   ✅ Leaked containers removed."
    else
       echo "   ⚠️  Run with --force or --all to remove these."
    fi
fi

LEAKED_NETWORKS=$($RUNTIME network ls --format "{{.Name}}" | grep "finance-report-internal" || true)
if [ -n "$LEAKED_NETWORKS" ]; then
    echo "   Found leaked networks:"
    echo "$LEAKED_NETWORKS" | sed 's/^/   - /'
    if [[ "${1:-}" == "--all" || "${1:-}" == "--force" ]]; then
       echo "$LEAKED_NETWORKS" | xargs $RUNTIME network rm 2>/dev/null || true
       echo "   ✅ Leaked networks removed."
    else
       echo "   ⚠️  Run with --force or --all to remove these."
    fi
fi

# 4. Clean up lock files and cache
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/finance_report"
if [ -d "$CACHE_DIR" ]; then
    echo "🔒 Cleaning up lock files in $CACHE_DIR..."
    rm -rf "$CACHE_DIR"
    echo "   ✅ Removed lock files."
fi

echo ""
echo "✨ Cleanup complete. Try running your tests/CI again."
echo ""
if [[ "${1:-}" == "--all" ]]; then
    echo "⚠️  Note: ALL DATA WAS DELETED. You'll need to re-run migrations on next dev server start."
fi

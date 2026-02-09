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

# Parse arguments
FORCE=0
ALL=0

while [[ "$#" -gt 0 ]]; do
    case "${1}" in
        --force) FORCE=1 ;;
        --all) ALL=1 ;;
        *) echo "⚠️  Unknown parameter: ${1}"; exit 1 ;;
    esac
    shift
done

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
    # Remove specific service containers
    for SERVICE in "${SERVICES[@]}"; do
        CONTAINERS=$($RUNTIME ps -a --filter "name=${SERVICE}" --format "{{.ID}}")
        if [ -n "$CONTAINERS" ]; then
            echo "   Found containers for $SERVICE. Removing..."
            echo "$CONTAINERS" | xargs $RUNTIME rm -f
        fi
    done
    
    # Remove Podman Pods if applicable
    if [ "$RUNTIME" == "podman" ]; then
        echo "📦 Checking for Podman Pods (pod_finance[-_]report*)..."
        PODS=$(podman pod ls --format "{{.Name}}" | grep -E "pod_finance[-_]report" || true)
        if [ -n "$PODS" ]; then
            echo "   Found leaked pods:"
            echo "$PODS" | sed 's/^/   - /'
            if [[ $ALL -eq 1 || $FORCE -eq 1 ]]; then
                echo "$PODS" | xargs podman pod rm -f
                echo "   ✅ Leaked pods removed."
            else
                echo "   ⚠️  Run with --force or --all to remove these pods."
            fi
        fi
    fi
    echo "   ✅ Specific containers cleaned."
    
    if [[ $ALL -eq 1 ]]; then
        echo "   🗑️  Removing volumes (THIS WILL DELETE ALL DATA)..."
        # Match finance-report, finance_report, and varied suffixes
        $RUNTIME volume ls --format "{{.Name}}" | grep -E "finance[-_]report" | xargs -r $RUNTIME volume rm 2>/dev/null || true
        echo "   ✅ Volumes removed."

# ... (rest of the file remains same, I'll just use multi_replace for multiple chunks or be careful)
        
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
    if [[ $FORCE -eq 1 ]]; then
        kill $PIDS 2>/dev/null || true
        echo "       Killed."
    fi
fi

# 3. Clean up leaked CI/Test containers/networks (finance-report-internal-*)
if [ -n "$RUNTIME" ]; then
    echo "🕵️  Checking for leaked CI/Test resources (finance-report-internal-*)..."

    LEAKED_CONTAINERS=$($RUNTIME ps -a --format "{{.Names}}" | grep "^finance-report-internal-" || true)
    if [ -n "$LEAKED_CONTAINERS" ]; then
        echo "   Found leaked containers:"
        echo "$LEAKED_CONTAINERS" | sed 's/^/   - /'
        if [[ $ALL -eq 1 || $FORCE -eq 1 ]]; then
           echo "$LEAKED_CONTAINERS" | xargs $RUNTIME rm -f
           echo "   ✅ Leaked containers removed."
        else
           echo "   ⚠️  Run with --force or --all to remove these."
        fi
    fi

    LEAKED_NETWORKS=$($RUNTIME network ls --format "{{.Name}}" | grep "^finance-report-internal-" || true)
    if [ -n "$LEAKED_NETWORKS" ]; then
        echo "   Found leaked networks:"
        echo "$LEAKED_NETWORKS" | sed 's/^/   - /'
        if [[ $ALL -eq 1 || $FORCE -eq 1 ]]; then
           echo "$LEAKED_NETWORKS" | xargs $RUNTIME network rm 2>/dev/null || true
           echo "   ✅ Leaked networks removed."
        else
           echo "   ⚠️  Run with --force or --all to remove these."
        fi
    fi
else
    echo "🕵️  Skipping leaked CI/Test resource check (no container runtime)."
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
if [[ $ALL -eq 1 ]]; then
    echo "⚠️  Note: ALL DATA WAS DELETED. You'll need to re-run migrations on next dev server start."
fi

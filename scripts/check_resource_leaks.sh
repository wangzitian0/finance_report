#!/usr/bin/env bash
# scripts/check_resource_leaks.sh
#
# Monitor and report potential resource leaks across all 6 environments.
# Run this weekly or after large test campaigns to detect accumulation.
#
# Usage:
#   ./scripts/check_resource_leaks.sh [--verbose]

set -e

VERBOSE=false
if [[ "${1:-}" == "--verbose" ]]; then
    VERBOSE=true
fi

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

echo "🔍 Finance Report - Resource Leak Detection"
echo "=========================================="
echo ""

ISSUES_FOUND=0

log_check() {
    echo -e "${1}"
}

log_ok() {
    echo -e "${GREEN}✓${RESET} ${1}"
}

log_warning() {
    echo -e "${YELLOW}⚠${RESET} ${1}"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
}

log_error() {
    echo -e "${RED}✗${RESET} ${1}"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
}

if command -v docker >/dev/null 2>&1; then
    RUNTIME="docker"
elif command -v podman >/dev/null 2>&1; then
    RUNTIME="podman"
else
    RUNTIME=""
fi

echo "📦 1. Local Environment - Worker Databases"
echo "-------------------------------------------"

if [ -n "$RUNTIME" ]; then
    DB_CONTAINER=$($RUNTIME ps -q -f "name=finance-report-db" || true)
    
    if [ -n "$DB_CONTAINER" ]; then
        WORKER_DBS=$($RUNTIME exec finance-report-db psql -U postgres -t -c \
            "SELECT count(*) FROM pg_database WHERE datname LIKE 'finance_report_test_%_gw%'" 2>/dev/null || echo "0")
        WORKER_DBS=$(echo "$WORKER_DBS" | tr -d ' ')
        
        if [ "$WORKER_DBS" -eq 0 ]; then
            log_ok "No orphaned worker databases"
        else
            log_warning "Found $WORKER_DBS orphaned worker databases"
            echo "   Fix: python scripts/cleanup_orphaned_dbs.py"
        fi
        
        if [ "$VERBOSE" = true ]; then
            echo "   Total test databases:"
            $RUNTIME exec finance-report-db psql -U postgres -t -c \
                "SELECT datname FROM pg_database WHERE datname LIKE 'finance_report_test_%'" 2>/dev/null || true
        fi
    else
        log_ok "Database container not running (no local leaks possible)"
    fi
else
    log_ok "No container runtime found (skipping local checks)"
fi

echo ""
echo "💾 2. Local Environment - Docker Volumes"
echo "-------------------------------------------"

if [ -n "$RUNTIME" ]; then
    VOLUME_COUNT=$($RUNTIME volume ls --format "{{.Name}}" | grep -c "finance.*report" || echo "0")
    VOLUME_SIZE=$($RUNTIME system df -v 2>/dev/null | grep "Local Volumes" | awk '{print $3,$4}' || echo "unknown")
    
    log_check "Total volumes: $VOLUME_COUNT (Size: $VOLUME_SIZE)"
    
    if [ "$VOLUME_COUNT" -gt 10 ]; then
        log_warning "Unusually high volume count ($VOLUME_COUNT volumes)"
        echo "   Review: $RUNTIME volume ls | grep finance"
    fi
    
    if [ "$VERBOSE" = true ]; then
        echo "   Volume list:"
        $RUNTIME volume ls --format "{{.Name}}" | grep "finance" || true
    fi
fi

echo ""
echo "🗂️  3. Local Environment - MinIO Data"
echo "-------------------------------------------"

if [ -n "$RUNTIME" ]; then
    MINIO_CONTAINER=$($RUNTIME ps -q -f "name=finance-report-minio" || true)
    
    if [ -n "$MINIO_CONTAINER" ]; then
        MINIO_SIZE=$($RUNTIME exec finance-report-minio du -sh /data 2>/dev/null | awk '{print $1}' || echo "unknown")
        log_check "MinIO data size: $MINIO_SIZE"
        
        if [ "$VERBOSE" = true ]; then
            echo "   Bucket list:"
            $RUNTIME exec finance-report-minio sh -c '
                mc alias set local http://localhost:9000 ${MINIO_ROOT_USER} ${MINIO_ROOT_PASSWORD} 2>/dev/null
                mc ls local/ 2>/dev/null
            ' || echo "   (Unable to list buckets)"
        fi
    else
        log_ok "MinIO container not running"
    fi
fi

echo ""
echo "🐳 4. VPS - PR Preview Volumes"
echo "-------------------------------------------"

if command -v ssh >/dev/null 2>&1 && [ -n "${VPS_HOST:-}" ]; then
    PR_VOLUMES=$(ssh -o ConnectTimeout=5 root@"$VPS_HOST" \
        "docker volume ls --format '{{.Name}}' | grep -c '\-pr-' || echo '0'" 2>/dev/null || echo "ssh_failed")
    
    # Trim whitespace for comparison
    PR_VOLUMES=$(echo "$PR_VOLUMES" | tr -d '[:space:]')
    
    if [ "$PR_VOLUMES" = "ssh_failed" ]; then
        log_check "VPS unreachable (set VPS_HOST=cloud.zitian.party to check)"
    elif [ "$PR_VOLUMES" -eq 0 ] 2>/dev/null; then
        log_ok "No orphaned PR volumes on VPS"
    else
        log_warning "Found $PR_VOLUMES orphaned PR volumes on VPS"
        echo "   These should be cleaned by pr-test.yml cleanup job"
        if [ "$VERBOSE" = true ]; then
            ssh root@"$VPS_HOST" "docker volume ls | grep '\-pr-'" || true
        fi
    fi
else
    log_check "VPS check skipped (SSH not available or VPS_HOST not set)"
fi

echo ""
echo "📦 5. GHCR - PR Preview Images"
echo "-------------------------------------------"

if command -v gh >/dev/null 2>&1; then
    for service in backend frontend; do
        API_RESPONSE=$(gh api "/orgs/wangzitian0/packages/container/finance_report-${service}/versions" 2>&1 || echo "api_failed")
        
        if echo "$API_RESPONSE" | grep -q "Not Found"; then
            log_ok "No GHCR package exists for ${service} (clean state)"
        elif [ "$API_RESPONSE" = "api_failed" ] || echo "$API_RESPONSE" | grep -q "api_failed"; then
            log_check "GHCR check failed for ${service} (check GitHub token permissions)"
        else
            PR_IMAGES=$(echo "$API_RESPONSE" | jq '[.[] | select(.metadata.container.tags[]? | contains("pr-"))] | length' 2>/dev/null || echo "0")
            
            if [ "$PR_IMAGES" -eq 0 ] 2>/dev/null; then
                log_ok "No orphaned PR images for ${service}"
            else
                log_warning "Found $PR_IMAGES orphaned PR images for ${service}"
                echo "   These should be cleaned by pr-test.yml cleanup job"
                if [ "$VERBOSE" = true ]; then
                    echo "$API_RESPONSE" | jq '.[] | select(.metadata.container.tags[]? | contains("pr-")) | .metadata.container.tags[0]' 2>/dev/null || true
                fi
            fi
        fi
    done
else
    log_check "GHCR check skipped (gh CLI not installed)"
fi

echo ""
echo "🔒 6. Cache Files"
echo "-------------------------------------------"

CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/finance_report"
if [ -d "$CACHE_DIR" ]; then
    ACTIVE_NAMESPACES=$(cat "$CACHE_DIR/active_namespaces.json" 2>/dev/null || echo "[]")
    NS_COUNT=$(echo "$ACTIVE_NAMESPACES" | grep -o '\"' | wc -l)
    NS_COUNT=$((NS_COUNT / 2))
    
    log_check "Active namespaces tracked: $NS_COUNT"
    
    if [ "$NS_COUNT" -gt 5 ]; then
        log_warning "Unusually high active namespace count ($NS_COUNT)"
        echo "   This may indicate interrupted test runs"
        echo "   Review: cat $CACHE_DIR/active_namespaces.json"
    fi
    
    if [ "$VERBOSE" = true ]; then
        echo "   Active namespaces:"
        cat "$CACHE_DIR/active_namespaces.json" 2>/dev/null || echo "   (empty)"
    fi
else
    log_ok "No cache directory (clean state)"
fi

echo ""
echo "=========================================="
if [ $ISSUES_FOUND -eq 0 ]; then
    echo -e "${GREEN}✅ No resource leaks detected${RESET}"
    exit 0
else
    echo -e "${YELLOW}⚠️  Found $ISSUES_FOUND potential issue(s)${RESET}"
    echo ""
    echo "Recommended actions:"
    echo "  1. Clean orphaned worker DBs:  python scripts/cleanup_orphaned_dbs.py"
    echo "  2. Clean all local resources:  ./scripts/cleanup_dev_resources.sh --all"
    echo "  3. Review PR cleanup logs in GitHub Actions"
    echo ""
    exit 1
fi

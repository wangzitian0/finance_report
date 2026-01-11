#!/usr/bin/env bash
# Smoke tests for Finance Report
# Usage: bash scripts/smoke_test.sh [BASE_URL]
#
# This script is used by both local development and CI.
# It verifies that the core endpoints are accessible.

set -euo pipefail

BASE_URL="${1:-http://localhost:3000}"

echo "========================================"
echo "Running smoke tests against $BASE_URL"
echo "========================================"

# Helper function
check_endpoint() {
    local name="$1"
    local url="$2"
    local expected="${3:-}"
    
    if [ -n "$expected" ]; then
        if curl -sf "$url" 2>/dev/null | grep -q "$expected"; then
            echo "✓ $name"
            return 0
        fi
    else
        if curl -sf -o /dev/null "$url" 2>/dev/null; then
            echo "✓ $name"
            return 0
        fi
    fi
    
    echo "✗ $name (failed)"
    return 1
}

# Run tests
FAILED=0

check_endpoint "Homepage" "$BASE_URL/" || FAILED=1
check_endpoint "API Health" "$BASE_URL/api/health" "healthy" || FAILED=1
check_endpoint "API Docs" "$BASE_URL/api/docs" || FAILED=1
check_endpoint "Ping-Pong Page" "$BASE_URL/ping-pong" || FAILED=1
check_endpoint "Reconciliation Page" "$BASE_URL/reconciliation" || FAILED=1
check_endpoint "Ping API" "$BASE_URL/api/ping" || FAILED=1

echo "========================================"
if [ "$FAILED" -eq 0 ]; then
    echo "All smoke tests passed!"
    exit 0
else
    echo "Some smoke tests failed!"
    exit 1
fi

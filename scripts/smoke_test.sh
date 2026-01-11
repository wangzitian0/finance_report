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
    
    local curl_output
    local curl_exit=0
    local http_code=""
    local content=""

    # Run curl once, capture both body and HTTP status code
    # The last line of output will be the HTTP status code, preceding lines are the body.
    curl_output="$(curl -sS -w $'\n%{http_code}' "$url" 2>&1)" || curl_exit=$?
    http_code="${curl_output##*$'\n'}"
    content="${curl_output%$'\n'"$http_code"}"

    if [ -n "$expected" ]; then
        # Check for expected content (substring match) and success status
        if [ "$curl_exit" -eq 0 ] && [ "$http_code" -ge 200 ] && [ "$http_code" -lt 400 ] && \
           printf '%s\n' "$content" | grep -Fq -- "$expected"; then
            echo "✓ $name"
            return 0
        fi
    else
        # Treat 2xx and 3xx as success when curl itself succeeded
        if [ "$curl_exit" -eq 0 ] && [ "$http_code" -ge 200 ] && [ "$http_code" -lt 400 ]; then
            echo "✓ $name"
            return 0
        fi
    fi
    
    echo "✗ $name (failed)"
    echo "  URL: $url"
    if [ -n "$http_code" ]; then
        echo "  HTTP status: $http_code"
    fi
    if [ "$curl_exit" -ne 0 ]; then
        echo "  curl exit code: $curl_exit"
    fi
    if [ -n "$expected" ]; then
        echo "  Expected to find: $expected"
    fi
    if [ -n "$content" ]; then
        echo "  Response snippet (first 5 lines):"
        printf '%s\n' "$content" | head -n 5
    fi
    return 1
}

# Run tests
FAILED=0

check_endpoint "Homepage (redirects to dashboard)" "$BASE_URL/" || FAILED=1
check_endpoint "Dashboard" "$BASE_URL/dashboard" || FAILED=1
check_endpoint "Accounts Page" "$BASE_URL/accounts" || FAILED=1
check_endpoint "Journal Page" "$BASE_URL/journal" || FAILED=1
check_endpoint "Statements Page" "$BASE_URL/statements" || FAILED=1
check_endpoint "Reports Page" "$BASE_URL/reports" || FAILED=1
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

#!/usr/bin/env bash
# Smoke tests for Finance Report
# Usage: bash scripts/smoke_test.sh [BASE_URL] [MODE]
#
# Arguments:
#   BASE_URL: The root URL of the application (default: http://localhost:3000)
#   MODE:     The environment mode: 'prod', 'staging', 'dev' (default: prod)
#             - prod: Read-only checks only. Safe for production.
#             - staging/dev: Includes write/mutation checks.

set -euo pipefail

BASE_URL="${1:-http://localhost:3000}"
MODE="${2:-prod}"

echo "========================================"
echo "Running smoke tests against $BASE_URL"
echo "Mode: $MODE"
echo "========================================"

# Helper function
check_endpoint() {
    local name="$1"
    local url="$2"
    local expected="${3:-}"
    local method="${4:-GET}"
    local data="${5:-}"
    
    local curl_opts=("-sS" "-w" "\n%{http_code}")
    if [ "$method" != "GET" ]; then
        curl_opts+=("-X" "$method")
    fi
    if [ -n "$data" ]; then
        curl_opts+=("-H" "Content-Type: application/json" "-d" "$data")
    fi

    local curl_output
    local curl_exit=0
    local http_code=""
    local content=""

    # Run curl once, capture both body and HTTP status code
    curl_output="$(curl "${curl_opts[@]}" "$url" 2>&1)" || curl_exit=$?
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
    echo "  Method: $method"
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

# Wait for app/API to become reachable before running checks
wait_for_endpoint() {
    local name="$1"
    local url="$2"
    local max_attempts="${SMOKE_READY_ATTEMPTS:-30}"
    local sleep_seconds="${SMOKE_READY_SLEEP_SECONDS:-5}"
    local attempt=1

    while [ "$attempt" -le "$max_attempts" ]; do
        local http_code="000"
        http_code="$(curl -sS -o /dev/null -w "%{http_code}" "$url" || true)"
        if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 400 ]; then
            echo "✓ Ready: $name ($http_code)"
            return 0
        fi
        echo "Waiting for $name ($url) - attempt $attempt/$max_attempts (status $http_code)..."
        sleep "$sleep_seconds"
        attempt=$((attempt + 1))
    done

    echo "✗ Timed out waiting for $name ($url)"
    return 1
}

# Run tests
FAILED=0

# --- Readiness Check ---
echo "--- Readiness Check ---"
wait_for_endpoint "API Health" "$BASE_URL/api/health" || FAILED=1

# --- Read-Only Checks (All Modes) ---
echo "--- Read-Only Checks ---"
check_endpoint "Homepage (redirects to dashboard)" "$BASE_URL/" || FAILED=1
check_endpoint "Dashboard" "$BASE_URL/dashboard" || FAILED=1
check_endpoint "Accounts Page" "$BASE_URL/accounts" || FAILED=1
check_endpoint "Journal Page" "$BASE_URL/journal" || FAILED=1
check_endpoint "Statements Page" "$BASE_URL/statements" || FAILED=1
check_endpoint "Reports Page" "$BASE_URL/reports" || FAILED=1
check_endpoint "API Health" "$BASE_URL/api/health" "healthy" || FAILED=1
check_endpoint "API Docs" "$BASE_URL/api/docs" || FAILED=1
check_endpoint "Reconciliation Page" "$BASE_URL/reconciliation" || FAILED=1
check_endpoint "Ping API" "$BASE_URL/api/ping" || FAILED=1

# --- Write/Mutation Checks (Staging/Dev Only) ---
if [ "$MODE" = "dev" ] || [ "$MODE" = "staging" ]; then
    echo "--- Write Checks ($MODE) ---"
    # Placeholder for a write check. 
    # Currently, we don't have a dedicated public 'safe' write endpoint for smoke tests 
    # without auth tokens. If auth is needed, this script would need a token.
    # For now, we will just echo that we are skipping complex write tests in this shell script
    # and relying on the Python E2E suite for that.
    echo "ℹ️  Complex write tests are delegated to the Python E2E suite."
    echo "✓ Write Mode Enabled (Placeholder)"
else
    echo "--- Write Checks ---"
    echo "ℹ️  Skipping write checks in '$MODE' mode."
fi

echo "========================================"
if [ "$FAILED" -eq 0 ]; then
    echo "All smoke tests passed!"
    exit 0
else
    echo "Some smoke tests failed!"
    exit 1
fi

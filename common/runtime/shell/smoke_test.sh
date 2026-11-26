#!/usr/bin/env bash
# Smoke tests for Finance Report
# Usage: bash common/runtime/shell/smoke_test.sh [BASE_URL] [MODE]
#
# Ownership: invoked via `common/runtime/shell/smoke_test.sh` from `runtime-hooks.manifest.json` (#1535).
# Arguments:
#   BASE_URL: Root URL of the application (default: http://localhost:3000)
#   MODE:     'prod' (read-only) or 'staging'/'preview'/'dev' (includes safe non-prod POST check).
#             Defaults from $ENVIRONMENT when omitted, or 'prod' when unset.

set -euo pipefail

BASE_URL="${1:-http://localhost:3000}"
BASE_URL="${BASE_URL%/}"

# The hook runner of infra2-sdk sets APP_VERSION_REF.
EXPECTED_REF="${APP_VERSION_REF:-}"
ENV_LOWER="$(printf '%s' "${ENVIRONMENT:-}" | tr '[:upper:]' '[:lower:]')"
case "$ENV_LOWER" in
    preview|pr-*|staging|prod|production)
        if [ -z "$EXPECTED_REF" ]; then
            echo "✗ APP_VERSION_REF must be set when ENVIRONMENT=${ENVIRONMENT}"
            exit 2
        fi
        ;;
esac

if [ $# -ge 2 ] && [ -n "${2:-}" ]; then
    MODE="$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')"
else
    case "$ENV_LOWER" in
        ""|prod|production) MODE="prod" ;;
        staging|preview|dev|development|local_dev|pr-*) MODE="staging" ;;
        *)
            echo "✗ Unknown ENVIRONMENT '${ENVIRONMENT}' and no explicit MODE provided"
            exit 2
            ;;
    esac
fi

case "$MODE" in
    prod|staging|preview|dev) ;;
    *)
        echo "✗ Invalid MODE '$MODE' (expected prod, staging, preview, or dev)"
        exit 2
        ;;
esac

PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [ -z "$PYTHON_BIN" ]; then
    echo "✗ python3 is required for smoke validation"
    exit 2
fi

echo "========================================"
echo "Running smoke tests against $BASE_URL"
echo "Mode: $MODE (ENVIRONMENT=${ENVIRONMENT:-unset})"
echo "========================================"

check_endpoint() {
    CHECK_COUNT=$((CHECK_COUNT + 1))
    local name="$1"
    local url="$2"
    local expected="${3:-}"
    local method="${4:-GET}"
    local data="${5:-}"

    local curl_opts=("-sS" "--connect-timeout" "5" "--max-time" "15" "-w" $'\n%{http_code}')
    if [ "$method" != "GET" ]; then
        curl_opts+=("-X" "$method")
    fi
    if [ -n "$data" ]; then
        curl_opts+=("-H" "Content-Type: application/json" "-d" "$data")
    fi

    local curl_output=""
    local curl_exit=0
    local http_code=""
    local content=""

    curl_output="$(curl "${curl_opts[@]}" "$url" 2>&1)" || curl_exit=$?
    http_code="${curl_output##*$'\n'}"
    content="${curl_output%$'\n'"$http_code"}"

    if [ -n "$expected" ]; then
        if [ "$curl_exit" -eq 0 ] && [ "$http_code" -ge 200 ] && [ "$http_code" -lt 400 ] && \
           printf '%s\n' "$content" | grep -Fq -- "$expected"; then
            echo "✓ $name"
            return 0
        fi
    else
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

wait_for_endpoint() {
    CHECK_COUNT=$((CHECK_COUNT + 1))
    local name="$1"
    local url="$2"
    local max_attempts="${SMOKE_READY_ATTEMPTS:-30}"
    local sleep_seconds="${SMOKE_READY_SLEEP_SECONDS:-5}"
    local attempt=1

    while [ "$attempt" -le "$max_attempts" ]; do
        local http_code="000"
        http_code="$(curl -sS --connect-timeout 5 --max-time 15 -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || true)"
        if [[ "$http_code" =~ ^[0-9]+$ ]] && [ "$http_code" -ge 200 ] && [ "$http_code" -lt 400 ]; then
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

check_full_health() {
    CHECK_COUNT=$((CHECK_COUNT + 1))
    local url="$BASE_URL/api/health?full=1"
    local expected_commit=""
    if [ -n "$EXPECTED_REF" ]; then
        expected_commit="$(git rev-parse --verify --end-of-options "${EXPECTED_REF}^{commit}" 2>/dev/null || true)"
    fi

    local curl_output=""
    local curl_exit=0
    curl_output="$(curl -sS --connect-timeout 5 --max-time 15 -w $'\n%{http_code}' "$url" 2>&1)" || curl_exit=$?
    local http_code="${curl_output##*$'\n'}"
    local content="${curl_output%$'\n'"$http_code"}"

    if [ "$curl_exit" -ne 0 ] || [ "$http_code" != "200" ]; then
        echo "✗ Full dependency & version check failed (exit=$curl_exit HTTP=$http_code)"
        [ -n "$content" ] && printf '%s\n' "$content" | head -n 5
        return 1
    fi

    local py_out=""
    local py_exit=0
    py_out="$(printf '%s' "$content" | SMOKE_EXPECTED_REF="$EXPECTED_REF" SMOKE_EXPECTED_COMMIT="$expected_commit" SMOKE_ENVIRONMENT="${ENVIRONMENT:-}" "$PYTHON_BIN" -c '
import json, os, sys
raw = sys.stdin.read()
expected_ref = os.environ.get("SMOKE_EXPECTED_REF", "").strip()
expected_commit = os.environ.get("SMOKE_EXPECTED_COMMIT", "").strip()
env_name = os.environ.get("SMOKE_ENVIRONMENT", "").strip().lower()
data = json.loads(raw)
status_val = data.get("status") if isinstance(data, dict) else type(data).__name__
if not isinstance(data, dict) or status_val != "healthy":
    raise SystemExit(f"unhealthy payload: status={status_val}")
if expected_ref:
    actual_sha = str(data.get("git_sha") or "")
    if not actual_sha or not (actual_sha == expected_ref or (expected_commit and len(actual_sha) >= 7 and expected_commit.startswith(actual_sha))):
        unresolved = expected_commit or "unresolved"
        raise SystemExit(f"git_sha mismatch: expected={expected_ref} commit={unresolved} got={actual_sha!r}")
checks = data.get("checks")
if not isinstance(checks, dict) or not checks:
    raise SystemExit("health response contains no checks")
for dep in ("database", "object_storage"):
    entry = checks.get(dep)
    if not isinstance(entry, dict) or entry.get("status") != "present":
        raise SystemExit(f"mandatory check {dep!r} not present: {entry!r}")
for name, entry in checks.items():
    if isinstance(entry, dict) and entry.get("required") is True and entry.get("status") != "present":
        raise SystemExit(f"required check {name!r} failed: {entry!r}")
if env_name == "staging":
    md = checks.get("market_data")
    if not isinstance(md, dict) or md.get("status") != "present":
        raise SystemExit(f"staging market_data check not present: {md!r}")
git_sha = data.get("git_sha", "n/a")
print(f"git_sha={git_sha} checks={len(checks)}")
' 2>&1)" || py_exit=$?

    if [ "$py_exit" -ne 0 ]; then
        echo "✗ Full dependency & version check failed: $py_out"
        return 1
    fi
    echo "✓ Full dependency & version check ($py_out)"
    return 0
}

FAILED=0
CHECK_COUNT=0
MIN_CHECKS="${MIN_CHECKS:-10}"
case "$MIN_CHECKS" in
    ''|*[!0-9]*)
        echo "✗ MIN_CHECKS must be a non-negative integer, got '$MIN_CHECKS'"
        exit 2
        ;;
esac

echo "--- Readiness Check ---"
wait_for_endpoint "API Health" "$BASE_URL/api/health" || FAILED=1
wait_for_endpoint "Frontend Ready" "$BASE_URL/" || FAILED=1

echo "--- Dependency & Version Parity Check ---"
check_full_health || FAILED=1

echo "--- CORS Check ---"
FRONTEND_URL="${BASE_URL%/}"
if curl -sS --connect-timeout 5 --max-time 15 -I -X OPTIONS "$BASE_URL/api/health" \
    -H "Origin: $FRONTEND_URL" \
    -H "Access-Control-Request-Method: GET" \
    | grep -qi "Access-Control-Allow-Origin"; then
    echo "✓ CORS Headers ($FRONTEND_URL)"
else
    echo "✗ CORS Headers Missing ($FRONTEND_URL)"
    FAILED=1
fi

echo "--- Read-Only Route Checks ---"
check_endpoint "Home Page" "$BASE_URL/" || FAILED=1
check_endpoint "Settings Page" "$BASE_URL/settings" || FAILED=1
check_endpoint "Journal Page" "$BASE_URL/journal" || FAILED=1
check_endpoint "Statements Upload Page" "$BASE_URL/upload" || FAILED=1
check_endpoint "Reports Page" "$BASE_URL/reports" || FAILED=1
check_endpoint "API Docs" "$BASE_URL/api/docs" || FAILED=1
check_endpoint "Reconciliation Page" "$BASE_URL/reconciliation" || FAILED=1
check_endpoint "Login Page" "$BASE_URL/login" || FAILED=1

echo "--- Authentication Tests ---"
AUTH_TEST_CODE="$(curl -sS --connect-timeout 5 --max-time 15 -o /dev/null -w "%{http_code}" "$BASE_URL/api/statements" 2>/dev/null || echo "000")"
if [ "$AUTH_TEST_CODE" = "401" ] || [ "$AUTH_TEST_CODE" = "429" ]; then
    echo "✓ Protected endpoint is secured (HTTP $AUTH_TEST_CODE)"
else
    echo "✗ Protected endpoint returned $AUTH_TEST_CODE (expected 401 or 429)"
    FAILED=1
fi

if [ "$MODE" != "prod" ]; then
    echo "--- Non-Prod POST Round-Trip Check ($MODE) ---"
    CHECK_COUNT=$((CHECK_COUNT + 1))
    LOGIN_EXIT=0
    LOGIN_OUT="$(curl -sS --connect-timeout 5 --max-time 15 -X POST -H "Content-Type: application/json" \
        -d '{"email":"smoke-probe@example.com","password":"invalid-smoke-password"}' \
        -w $'\n%{http_code}' "$BASE_URL/api/auth/login" 2>&1)" || LOGIN_EXIT=$?
    LOGIN_CODE="${LOGIN_OUT##*$'\n'}"
    LOGIN_BODY="${LOGIN_OUT%$'\n'"$LOGIN_CODE"}"
    if [ "$LOGIN_EXIT" -eq 0 ] && { [ "$LOGIN_CODE" = "401" ] || [ "$LOGIN_CODE" = "429" ]; } && \
       printf '%s' "$LOGIN_BODY" | "$PYTHON_BIN" -c 'import json, sys; d = json.load(sys.stdin); assert isinstance(d, dict) and ("detail" in d or "error_id" in d)' 2>/dev/null; then
        echo "✓ Non-prod POST /api/auth/login round-trip (HTTP $LOGIN_CODE)"
    else
        echo "✗ Non-prod POST /api/auth/login round-trip failed (exit=$LOGIN_EXIT status=$LOGIN_CODE)"
        FAILED=1
    fi
fi

echo "========================================"
echo "Ran $CHECK_COUNT endpoint checks (minimum $MIN_CHECKS)"
if [ "$CHECK_COUNT" -lt "$MIN_CHECKS" ]; then
    echo "✗ smoke ran only $CHECK_COUNT endpoint checks (< $MIN_CHECKS) — refusing to report green"
    exit 1
fi
if [ "$FAILED" -eq 0 ]; then
    echo "All smoke tests passed!"
    exit 0
else
    echo "Some smoke tests failed!"
    exit 1
fi

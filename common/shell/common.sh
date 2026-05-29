#!/usr/bin/env bash
# Common deployment utilities
# Shared functions for deployment command entry points.
#
# Usage: source "$REPO_ROOT/common/shell/common.sh"

# Validate string is non-empty and not whitespace-only
# Fixes: CRITICAL-1 (whitespace-only env vars)
#
# Usage: validate_non_empty "$value" "variable_name" || exit 1
# Returns: 0 if valid, 1 if empty/whitespace
validate_non_empty() {
  local value="${1:-}"
  local name="${2:-variable}"
  
  # Strip all whitespace and check if empty
  if [[ -z "${value// }" ]]; then
    echo "ERROR: $name is empty or whitespace-only" >&2
    return 1
  fi
  return 0
}

# Safe jq wrapper with JSON validation
# Fixes: CRITICAL-2 (jq parse failures), CRITICAL-4 (hidden API errors)
#
# Usage: result=$(safe_jq '.field' "$json_string" "context") || exit 1
# Returns: Parsed value on success, exits with error message on failure
safe_jq() {
  local filter="$1"
  local input="${2:-}"
  local context="${3:-jq parse}"
  local jq_output_file
  local jq_stderr_file
  local exit_code
  
  jq_output_file=$(mktemp)
  jq_stderr_file=$(mktemp)
  
  echo "$input" | jq -r "$filter" >"$jq_output_file" 2>"$jq_stderr_file"
  exit_code=$?
  
  if [[ -s "$jq_stderr_file" ]] && grep -q "parse error" "$jq_stderr_file"; then
    echo "ERROR: jq failed in $context" >&2
    cat "$jq_stderr_file" >&2
    rm -f "$jq_output_file" "$jq_stderr_file"
    return 1
  fi
  
  if [[ $exit_code -eq 0 ]]; then
    cat "$jq_output_file"
    rm -f "$jq_output_file" "$jq_stderr_file"
    return 0
  fi
  
  echo "ERROR: jq failed in $context" >&2
  cat "$jq_stderr_file" >&2
  rm -f "$jq_output_file" "$jq_stderr_file"
  return 1
}

# Safe jq for creating JSON payloads (no input needed)
# Fixes: CRITICAL-2 (jq build failures)
#
# Usage: payload=$(safe_jq_build '{foo: $bar}' --arg bar "value") || exit 1
safe_jq_build() {
  local result
  if ! result=$(jq -n "$@" 2>&1); then
    echo "ERROR: jq build failed: $*" >&2
    return 1
  fi
  echo "$result"
}

# Check HTTP status code with numeric comparison
# Fixes: CRITICAL-7 (string comparison for HTTP codes)
#
# Usage: check_http_code "$code" "200" "API call" || exit 1
check_http_code() {
  local actual="${1:-000}"
  local expected="${2:-200}"
  local context="${3:-HTTP request}"
  
  # Numeric comparison (handles "200 " vs "200" edge cases)
  if ! [[ "$actual" =~ ^[0-9]+$ ]] || [[ "$actual" -ne "$expected" ]]; then
    echo "ERROR: $context returned HTTP $actual (expected $expected)" >&2
    return 1
  fi
  return 0
}

# Setup temp files with safe cleanup
# Fixes: CRITICAL-6 (temp file cleanup race condition)
#
# Usage: 
#   response_file=$(mktemp)
#   error_file=$(mktemp)
#   register_cleanup "$response_file" "$error_file"
#
# Note: Registers cleanup trap that ignores errors
register_cleanup() {
  local files=("$@")
  # shellcheck disable=SC2064
  trap "rm -f ${files[*]} 2>/dev/null || true" EXIT INT TERM
}

# Escape environment variable value for safe shell injection
# Fixes: CRITICAL-3 (unsafe special characters in env vars)
#
# Usage: safe_value=$(escape_env_value "$raw_value")
# Returns: JSON-encoded string safe for shell variables
escape_env_value() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  echo "$value"
}

# Validate health response using proper JSON parsing
# Fixes: CRITICAL-5 (string matching false positives)
#
# Usage: validate_health_response "$response" || exit 1
# Returns: 0 if healthy, 1 otherwise
validate_health_response() {
  local response="$1"
  
  # Parse as JSON and check status field explicitly
  if ! echo "$response" | jq -e '.status == "healthy"' >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

# Call Dokploy API with comprehensive error handling
# Fixes: CRITICAL-4 (pipe errors hidden), CRITICAL-7 (HTTP comparison)
#
# Usage: dokploy_api_call "GET" "endpoint" "" "$output_file" "context"
#        dokploy_api_call "POST" "endpoint" "$json_payload" "$output_file" "context"
#
# Environment: Requires DOKPLOY_API_KEY, DOKPLOY_API_URL
# Returns: 0 on success (HTTP 200), exits on error
dokploy_api_call() {
  local method="$1"
  local endpoint="$2"
  local data="${3:-}"
  local output_file="${4:-}"
  local error_context="${5:-API call}"
  
  # Validate inputs
  validate_non_empty "$method" "HTTP method" || return 1
  validate_non_empty "$endpoint" "API endpoint" || return 1
  validate_non_empty "$output_file" "output file" || return 1
  validate_non_empty "${DOKPLOY_API_KEY:-}" "DOKPLOY_API_KEY" || return 1
  validate_non_empty "${DOKPLOY_API_URL:-}" "DOKPLOY_API_URL" || return 1
  
  local error_file
  error_file=$(mktemp)
  register_cleanup "$error_file"
  
  local curl_args=(
    -s
    -o "$output_file"
    -w "%{http_code}"
    -H "x-api-key: $DOKPLOY_API_KEY"
  )
  
  if [[ "$method" == "POST" ]]; then
    curl_args+=(-X POST -H "Content-Type: application/json")
    if [[ -n "$data" ]]; then
      curl_args+=(-d "$data")
    fi
  fi
  
  curl_args+=("$DOKPLOY_API_URL/$endpoint")
  
  # Capture HTTP code and handle connection errors
  local http_code
  http_code=$(curl "${curl_args[@]}" 2>"$error_file" || echo "000")
  
  # Check for connection failures
  if [[ "$http_code" == "000" ]]; then
    echo "ERROR: Failed to connect to Dokploy API ($error_context)" >&2
    cat "$error_file" >&2
    return 1
  fi
  
  # Validate HTTP status code
  if ! check_http_code "$http_code" "200" "$error_context"; then
    echo "Response body:" >&2
    cat "$output_file" >&2
    return 1
  fi
  
  return 0
}

# Update environment variable in multi-line env string
# Fixes: CRITICAL-3 (uses escape_env_value for safety)
#
# Usage: new_env=$(update_env_var "$current_env" "VAR_NAME" "$value")
update_env_var() {
  local env_content="$1"
  local var_name="$2"
  local var_value="$3"
  
  # Escape the value for safe injection
  local safe_value
  safe_value=$(escape_env_value "$var_value")
  
  # Update or append
  if echo "$env_content" | grep -q "^${var_name}="; then
    echo "$env_content" | sed "s|^${var_name}=.*|${var_name}=${safe_value}|"
  else
    printf "%s\n%s=%s" "$env_content" "$var_name" "$safe_value"
  fi
}

# Mask sensitive values from GitHub Actions logs
# Usage: mask_secrets "$env_string"
mask_secrets() {
  local env_content="$1"
  
  while IFS= read -r line; do
    case "$line" in
      VAULT_*=*|*TOKEN=*|*SECRET=*|*KEY=*|*PASSWORD=*)
        value=${line#*=}
        if [[ -n "$value" ]]; then
          echo "::add-mask::$value"
        fi
        ;;
    esac
  done <<< "$env_content"
}

# Verify a Dokploy-provided VAULT_APP_TOKEN before triggering deployment.
# This catches expired tokens before compose redeploy turns into a route-level 404.
verify_vault_app_token() {
  local env_content="$1"
  local context="${2:-Vault token preflight}"
  local min_ttl_seconds="${3:-86400}"
  local token=""
  local vault_addr=""
  local lookup_file
  local error_file
  local http_code
  local ttl
  local renewable

  while IFS= read -r line; do
    case "$line" in
      VAULT_APP_TOKEN=*) token="${line#VAULT_APP_TOKEN=}" ;;
      VAULT_ADDR=*) vault_addr="${line#VAULT_ADDR=}" ;;
    esac
  done <<< "$env_content"

  if [[ -z "$token" ]]; then
    echo "ERROR: $context failed: VAULT_APP_TOKEN is missing" >&2
    return 1
  fi

  if [[ -z "$vault_addr" ]]; then
    vault_addr="https://vault.zitian.party"
  fi

  lookup_file=$(mktemp)
  error_file=$(mktemp)

  http_code=$(curl -sS \
    -o "$lookup_file" \
    -w "%{http_code}" \
    -H "X-Vault-Token: $token" \
    "$vault_addr/v1/auth/token/lookup-self" \
    2>"$error_file" || echo "000")

  if [[ "$http_code" == "000" ]]; then
    echo "ERROR: $context failed: cannot connect to Vault at $vault_addr" >&2
    cat "$error_file" >&2
    rm -f "$lookup_file" "$error_file"
    return 1
  fi

  if ! check_http_code "$http_code" "200" "$context" 2>/dev/null; then
    echo "ERROR: $context failed: VAULT_APP_TOKEN is invalid or expired (HTTP $http_code)" >&2
    rm -f "$lookup_file" "$error_file"
    return 1
  fi

  ttl=$(safe_jq '.data.ttl // 0' "$(cat "$lookup_file")" "$context ttl") || {
    rm -f "$lookup_file" "$error_file"
    return 1
  }
  renewable=$(safe_jq '.data.renewable // false' "$(cat "$lookup_file")" "$context renewable") || {
    rm -f "$lookup_file" "$error_file"
    return 1
  }

  rm -f "$lookup_file" "$error_file"

  if [[ "$renewable" != "true" ]]; then
    echo "ERROR: $context failed: VAULT_APP_TOKEN is not renewable" >&2
    return 1
  fi

  if ! [[ "$ttl" =~ ^[0-9]+$ ]] || (( ttl < min_ttl_seconds )); then
    echo "ERROR: $context failed: VAULT_APP_TOKEN ttl ${ttl}s is below required ${min_ttl_seconds}s" >&2
    return 1
  fi

  echo "Vault token preflight passed: ttl=${ttl}s renewable=$renewable"
  return 0
}

#!/usr/bin/env bash
# Dokploy Deployment Script - Unified deployment operations
#
# Usage:
#   ./scripts/dokploy_deploy.sh <compose_id> <image_tag> <app_url>
#
# Arguments:
#   compose_id - Dokploy compose ID
#   image_tag  - Docker image tag to deploy
#   app_url    - Application URL (e.g., https://report.zitian.party)
#
# Environment Variables (required):
#   DOKPLOY_API_KEY - Dokploy API key
#   DOKPLOY_API_URL - Dokploy API base URL
#
# Exit codes:
#   0 - Deployment triggered successfully
#   1 - Deployment failed

set -euo pipefail

# Collect all missing requirements
missing_args=()
missing_envs=()

COMPOSE_ID="${1:-}"
IMAGE_TAG="${2:-}"
APP_URL="${3:-}"

[ -z "$COMPOSE_ID" ] && missing_args+=("compose_id")
[ -z "$IMAGE_TAG" ] && missing_args+=("image_tag")
[ -z "$APP_URL" ] && missing_args+=("app_url")

[ -z "${DOKPLOY_API_KEY:-}" ] && missing_envs+=("DOKPLOY_API_KEY")
[ -z "${DOKPLOY_API_URL:-}" ] && missing_envs+=("DOKPLOY_API_URL")

# Report all missing requirements at once
if [ ${#missing_args[@]} -gt 0 ] || [ ${#missing_envs[@]} -gt 0 ]; then
  echo "========================================="
  echo "ERROR: Missing Required Dependencies"
  echo "========================================="
  
  if [ ${#missing_args[@]} -gt 0 ]; then
    echo ""
    echo "Missing Arguments:"
    for arg in "${missing_args[@]}"; do
      echo "  - $arg"
    done
    echo ""
    echo "Usage: $0 <compose_id> <image_tag> <app_url>"
  fi
  
  if [ ${#missing_envs[@]} -gt 0 ]; then
    echo ""
    echo "Missing Environment Variables:"
    for env in "${missing_envs[@]}"; do
      echo "  - $env"
    done
    echo ""
    echo "Required in workflow step 'env:' section"
  fi
  
  echo "========================================="
  exit 1
fi

echo "Deploying $IMAGE_TAG to compose $COMPOSE_ID..."

# Setup temp files
response_file=$(mktemp)
error_file=$(mktemp)
trap 'rm -f "$response_file" "$error_file"' EXIT INT TERM

# Function to call Dokploy API with error handling
function dokploy_api_call {
  local method="$1"
  local endpoint="$2"
  local data="${3:-}"
  local output_file="${4:-$response_file}"
  local error_context="${5:-API call}"
  
  local curl_args=(
    -s
    -o "$output_file"
    -w "%{http_code}"
    -H "x-api-key: $DOKPLOY_API_KEY"
  )
  
  if [ "$method" = "POST" ]; then
    curl_args+=(-X POST -H "Content-Type: application/json")
    if [ -n "$data" ]; then
      curl_args+=(-d "$data")
    fi
  fi
  
  curl_args+=("$DOKPLOY_API_URL/$endpoint")
  
  http_code=$(curl "${curl_args[@]}" 2>"$error_file" || echo "000")
  
  if [ "$http_code" = "000" ]; then
    echo "ERROR: Failed to connect to Dokploy API ($error_context)"
    cat "$error_file"
    exit 1
  elif [ "$http_code" != "200" ]; then
    echo "ERROR: $error_context failed with HTTP $http_code"
    cat "$output_file"
    exit 1
  fi
}

# Get current environment variables
dokploy_api_call "GET" "compose.one?composeId=$COMPOSE_ID" "" "$response_file" "Fetch environment"

env_response=$(cat "$response_file")

if [ -z "$env_response" ]; then
  echo "ERROR: Empty response from API"
  exit 1
fi

current_env=$(echo "$env_response" | jq -r '.env // empty')

# Mask sensitive values from GitHub Actions logs
function mask_secrets {
  while IFS= read -r line; do
    case "$line" in
      VAULT_*=*|[A-Z_]*TOKEN=*|[A-Z_]*SECRET=*|[A-Z_]*KEY=*|[A-Z_]*PASSWORD=*)
        value=${line#*=}
        if [ -n "$value" ]; then
          echo "::add-mask::$value"
        fi
        ;;
    esac
  done <<< "$current_env"
}

mask_secrets

function update_env_var {
  local env_content="$1"
  local var_name="$2"
  local var_value="$3"
  
  if echo "$env_content" | grep -q "^${var_name}="; then
    echo "$env_content" | sed "s|^${var_name}=.*|${var_name}=${var_value}|"
  else
    printf "%s\n%s=%s" "$env_content" "$var_name" "$var_value"
  fi
}

new_env="$current_env"
new_env=$(update_env_var "$new_env" "IMAGE_TAG" "$IMAGE_TAG")
new_env=$(update_env_var "$new_env" "NEXT_PUBLIC_APP_URL" "$APP_URL")

update_response_file=$(mktemp)
update_error_file=$(mktemp)
trap 'rm -f "$response_file" "$error_file" "$update_response_file" "$update_error_file"' EXIT INT TERM

payload=$(jq -n --arg id "$COMPOSE_ID" --arg env "$new_env" '{composeId: $id, env: $env}')
dokploy_api_call "POST" "compose.update" "$payload" "$update_response_file" "Environment update"

echo "Environment updated to use image tag: $IMAGE_TAG"

deploy_response_file=$(mktemp)
deploy_error_file=$(mktemp)
trap 'rm -f "$response_file" "$error_file" "$update_response_file" "$update_error_file" "$deploy_response_file" "$deploy_error_file"' EXIT INT TERM

deploy_payload=$(jq -n --arg id "$COMPOSE_ID" '{composeId: $id}')
dokploy_api_call "POST" "compose.deploy" "$deploy_payload" "$deploy_response_file" "Deployment trigger"

echo "Deployment triggered successfully"
exit 0

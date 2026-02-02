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

# shellcheck source=scripts/lib/common.sh
source "$(dirname "$0")/lib/common.sh"

missing_args=()
missing_envs=()

COMPOSE_ID="${1:-}"
IMAGE_TAG="${2:-}"
APP_URL="${3:-}"

validate_non_empty "$COMPOSE_ID" "compose_id" 2>/dev/null || missing_args+=("compose_id")
validate_non_empty "$IMAGE_TAG" "image_tag" 2>/dev/null || missing_args+=("image_tag")
validate_non_empty "$APP_URL" "app_url" 2>/dev/null || missing_args+=("app_url")

validate_non_empty "${DOKPLOY_API_KEY:-}" "DOKPLOY_API_KEY" 2>/dev/null || missing_envs+=("DOKPLOY_API_KEY")
validate_non_empty "${DOKPLOY_API_URL:-}" "DOKPLOY_API_URL" 2>/dev/null || missing_envs+=("DOKPLOY_API_URL")

if [[ ${#missing_args[@]} -gt 0 ]] || [[ ${#missing_envs[@]} -gt 0 ]]; then
  echo "========================================="
  echo "ERROR: Missing Required Dependencies"
  echo "========================================="
  
  if [[ ${#missing_args[@]} -gt 0 ]]; then
    echo ""
    echo "Missing Arguments:"
    printf '  - %s\n' "${missing_args[@]}"
    echo ""
    echo "Usage: $0 <compose_id> <image_tag> <app_url>"
  fi
  
  if [[ ${#missing_envs[@]} -gt 0 ]]; then
    echo ""
    echo "Missing Environment Variables:"
    printf '  - %s\n' "${missing_envs[@]}"
    echo ""
    echo "Required in workflow step 'env:' section"
  fi
  
  echo "========================================="
  exit 1
fi

echo "Deploying $IMAGE_TAG to compose $COMPOSE_ID..."

response_file=$(mktemp)
update_response_file=$(mktemp)
deploy_response_file=$(mktemp)
register_cleanup "$response_file" "$update_response_file" "$deploy_response_file"

dokploy_api_call "GET" "compose.one?composeId=$COMPOSE_ID" "" "$response_file" "Fetch environment"

env_response=$(cat "$response_file")

if ! validate_non_empty "$env_response" "API response"; then
  echo "ERROR: Empty response from API"
  exit 1
fi

current_env=$(safe_jq '.env // empty' "$env_response" "environment fetch") || exit 1

mask_secrets "$current_env"

new_env="$current_env"
new_env=$(update_env_var "$new_env" "IMAGE_TAG" "$IMAGE_TAG")
new_env=$(update_env_var "$new_env" "GIT_COMMIT_SHA" "$IMAGE_TAG")
new_env=$(update_env_var "$new_env" "NEXT_PUBLIC_APP_URL" "$APP_URL")
new_env=$(update_env_var "$new_env" "COMPOSE_PROFILES" "app")
new_env=$(update_env_var "$new_env" "TRAEFIK_ENABLE" "true")

# Traefik routing configuration
# Detect environment from APP_URL (staging/production)
if [[ "$APP_URL" == *"-staging"* ]]; then
  new_env=$(update_env_var "$new_env" "ENV_SUFFIX" "-staging")
  new_env=$(update_env_var "$new_env" "ENV_DOMAIN_SUFFIX" "-staging")
else
  new_env=$(update_env_var "$new_env" "ENV_SUFFIX" "")
  new_env=$(update_env_var "$new_env" "ENV_DOMAIN_SUFFIX" "")
fi
new_env=$(update_env_var "$new_env" "INTERNAL_DOMAIN" "zitian.party")

payload=$(safe_jq_build --arg id "$COMPOSE_ID" --arg env "$new_env" '{composeId: $id, env: $env}') || exit 1
dokploy_api_call "POST" "compose.update" "$payload" "$update_response_file" "Environment update"

echo "Environment updated to use image tag: $IMAGE_TAG"

deploy_payload=$(safe_jq_build --arg id "$COMPOSE_ID" '{composeId: $id}') || exit 1
dokploy_api_call "POST" "compose.deploy" "$deploy_payload" "$deploy_response_file" "Deployment trigger"

echo "Deployment triggered successfully"
exit 0

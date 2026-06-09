#!/usr/bin/env bash
# Dokploy Deployment Script - Unified deployment operations
#
# Usage:
#   ./tools/dokploy_deploy.sh <compose_id> <image_tag> <app_url>
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

# shellcheck source=common/shell/common.sh
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/common/shell/common.sh"

missing_args=()
missing_envs=()

COMPOSE_ID="${1:-}"
IMAGE_TAG="${2:-}"
APP_URL="${3:-}"

deployment_ids_from_response() {
  local response="$1"
  echo "$response" | jq -r '[
    (if (.deployments | type) == "array" then .deployments else [] end)[]
    | select(type == "object")
    | (.deploymentId? // empty)
    | tostring
  ] | join(",")'
}

new_deployment_ids_from_response() {
  local response="$1"
  local previous_deployment_ids="$2"
  echo "$response" | jq -r --arg previous ",$previous_deployment_ids," \
    '[
      (if (.deployments | type) == "array" then .deployments else [] end)[]
      | select(type == "object")
      | (.deploymentId? // empty)
      | tostring
      | . as $deployment_id
      | select(($previous | contains("," + $deployment_id + ",")) | not)
    ] | join(",")'
}

latest_new_deployment_status_from_response() {
  local response="$1"
  local new_deployment_ids="$2"
  echo "$response" | jq -r --arg ids ",$new_deployment_ids," \
    '[
      (if (.deployments | type) == "array" then .deployments else [] end)[]
      | select(type == "object")
      | select(.deploymentId? != null)
      | . + {deploymentId: (.deploymentId | tostring)}
      | .deploymentId as $deployment_id
      | select($ids | contains("," + $deployment_id + ","))
    ] | sort_by(.createdAt // .startedAt // .finishedAt // "") | (last // {}) | .status // "unknown"'
}

deployment_signature_map_from_response() {
  local response="$1"
  echo "$response" | jq -c 'reduce (if (.deployments | type) == "array" then .deployments else [] end)[] as $deployment ({ };
    if ($deployment | type) == "object" and ($deployment.deploymentId? != null) then
      .[$deployment.deploymentId | tostring] = [
        ($deployment.status // ""),
        ($deployment.createdAt // ""),
        ($deployment.startedAt // ""),
        ($deployment.finishedAt // "")
      ]
    else
      .
    end)'
}

deployment_count_from_response() {
  local response="$1"
  echo "$response" | jq -r '[
    (if (.deployments | type) == "array" then .deployments else [] end)[]
    | select(type == "object")
  ] | length'
}

redact_dokploy_diagnostic_value() {
  local value="$1"
  printf "%s" "$value" | perl -pe '
    s/\b(Bearer|Basic)\s+[A-Za-z0-9._~+\/\-]+=*/$1 <redacted>/gi;
    s/\bhvs\.[A-Za-z0-9._-]+/hvs.<redacted>/g;
    s/\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|AUTHORIZATION|COOKIE|DATABASE_URL|REFRESH)[A-Z0-9_]*\s*[:=]\s*)([^,\s]+)/$1<redacted>/gi;
  ' | head -c 300
}

latest_deployment_json_from_response() {
  local response="$1"
  echo "$response" | jq -c '[
    (if (.deployments | type) == "array" then .deployments else [] end)[]
    | select(type == "object")
  ] | sort_by(.createdAt // .startedAt // .finishedAt // "") | (last // {})'
}

render_dokploy_rollout_summary() {
  local response="$1"
  local label="$2"
  local key
  local value
  local latest

  echo "Dokploy rollout summary ($label)"
  for key in composeId name sourceType repository owner branch composePath command environmentId composeStatus status; do
    value=$(echo "$response" | jq -r --arg key "$key" '.[$key] // empty' 2>/dev/null | head -c 160)
    if [[ -n "$value" ]]; then
      echo "$key: $value"
    fi
  done
  echo "env_present: $(echo "$response" | jq -r 'has("env") and (.env != null and .env != "")' 2>/dev/null || echo false)"
  echo "deployment_count: $(deployment_count_from_response "$response" 2>/dev/null || echo unknown)"

  latest=$(latest_deployment_json_from_response "$response")
  if [[ "$latest" != "{}" ]]; then
    for key in deploymentId status createdAt startedAt finishedAt; do
      value=$(echo "$latest" | jq -r --arg key "$key" '.[$key] // empty' 2>/dev/null | head -c 160)
      if [[ -n "$value" ]]; then
        echo "latest_deployment_${key}: $(redact_dokploy_diagnostic_value "$value")"
      fi
    done
    value=$(echo "$latest" | jq -r '.logPath // empty' 2>/dev/null | head -c 160)
    if [[ -n "$value" ]]; then
      echo "latest_deployment_logPath: $(redact_dokploy_diagnostic_value "$value")"
    fi
    for key in message error errorMessage statusMessage statusReason reason description; do
      value=$(echo "$latest" | jq -r --arg key "$key" '.[$key] // empty' 2>/dev/null | head -c 300)
      if [[ -n "$value" ]]; then
        echo "latest_deployment_${key}: $(redact_dokploy_diagnostic_value "$value")"
      fi
    done
  fi
  echo "raw_compose_printed: false"
  echo "raw_deployment_printed: false"
}

wait_for_dokploy_deployment_rollout() {
  local compose_id="$1"
  local previous_deployment_ids="$2"
  local previous_deployment_signatures="${3:-{}}"
  local timeout_seconds="${DOKPLOY_ROLLOUT_TIMEOUT_SECONDS:-600}"
  local new_deployment_timeout_seconds="${DOKPLOY_NEW_DEPLOYMENT_TIMEOUT_SECONDS:-120}"
  local interval_seconds="${DOKPLOY_ROLLOUT_INTERVAL_SECONDS:-5}"
  local started="$SECONDS"
  local new_deployment_deadline=$((started + new_deployment_timeout_seconds))
  local attempt=0
  local rollout_response
  local compose_status
  local deployment_count
  local new_deployment_ids
  local current_deployment_signatures
  local existing_deployment_updates
  local latest_status
  local existing_deployment_status

  echo "Waiting for Dokploy deployment record before readiness polling..."
  echo "previous_deployment_ids=${previous_deployment_ids:-none}"

  while (( SECONDS - started <= timeout_seconds )); do
    attempt=$((attempt + 1))
    dokploy_api_call "GET" "compose.one?composeId=$compose_id" "" "$response_file" "Deployment rollout probe"
    rollout_response=$(cat "$response_file")
    compose_status=$(safe_jq '.composeStatus // .status // "unknown"' "$rollout_response" "deployment rollout compose status") || exit 1
    deployment_count=$(deployment_count_from_response "$rollout_response") || exit 1
    new_deployment_ids=$(new_deployment_ids_from_response "$rollout_response" "$previous_deployment_ids") || exit 1
    current_deployment_signatures=$(deployment_signature_map_from_response "$rollout_response")
    existing_deployment_updates=$(echo "$current_deployment_signatures" | jq -r --argjson prev "$previous_deployment_signatures" '
      [to_entries[]
      | select(.value != ($prev[.key] // []))
      | .key]
      | join(",")
    ')

    if (( attempt == 1 || attempt % 6 == 0 )) || [[ "$compose_status" != "idle" ]]; then
      render_dokploy_rollout_summary "$rollout_response" "deployment-rollout-attempt-$attempt"
    fi
    echo "Dokploy rollout attempt $attempt: composeStatus=$compose_status deployment_count=$deployment_count new_deployment_ids=${new_deployment_ids:-none}"

    if [[ "$compose_status" == "error" ]]; then
      render_dokploy_rollout_summary "$rollout_response" "compose-error-attempt-$attempt"
      if [[ -n "$new_deployment_ids" ]]; then
        echo "ERROR: Dokploy compose entered error before readiness polling" >&2
        exit 1
      fi
      echo "Dokploy compose still reports a stale error before the rollout has created a new deployment record; continuing rollout poll."
    fi

    if [[ -n "$new_deployment_ids" ]]; then
      latest_status=$(latest_new_deployment_status_from_response "$rollout_response" "$new_deployment_ids") || exit 1
      echo "Dokploy deployment observed: compose_id=$compose_id new_deployment_ids=$new_deployment_ids latest_deployment_status=$latest_status"
      if [[ "$latest_status" == "error" ]]; then
        render_dokploy_rollout_summary "$rollout_response" "deployment-error-attempt-$attempt"
        echo "ERROR: Dokploy deployment failed before readiness polling" >&2
        exit 1
      fi
      if [[ "$latest_status" == "done" ]]; then
        return 0
      fi
    elif [[ -n "$existing_deployment_updates" ]] && [[ "$compose_status" == "done" ]]; then
      existing_deployment_status=$(latest_new_deployment_status_from_response "$rollout_response" "$existing_deployment_updates") || exit 1
      echo "Dokploy deployment observed via existing deployment record update: compose_id=$compose_id existing_deployment_ids=$existing_deployment_updates latest_deployment_status=$existing_deployment_status"
      if [[ "$existing_deployment_status" == "done" ]]; then
        return 0
      fi
    fi

    if [[ -z "$new_deployment_ids" ]] && (( SECONDS >= new_deployment_deadline )); then
      project_id=$(echo "$rollout_response" | jq -r '.environment?.projectId? // empty' 2>/dev/null)
      if [[ -n "$project_id" ]]; then
        project_response_file=$(mktemp)
        if dokploy_api_call "GET" "project.one?projectId=$project_id" "" "$project_response_file" "Queue congestion check" 2>/dev/null; then
          running_count=$(cat "$project_response_file" | jq '[.environments[].compose[] | select(.composeStatus == "running" or .composeStatus == "deploying")] | length' 2>/dev/null || echo 0)
          rm -f "$project_response_file"
          if (( running_count > 0 )); then
            echo "Warning: Dokploy is currently busy with $running_count other deployments. Extending queue timeout."
            new_deployment_deadline=$((SECONDS + 60))
            sleep "$interval_seconds"
            continue
          fi
        else
          rm -f "$project_response_file"
        fi
      fi

      echo "ERROR: Dokploy deployment did not create a new deployment before readiness polling" >&2
      echo "compose_id=$compose_id composeStatus=${compose_status:-unknown} deployment_count=${deployment_count:-unknown}" >&2
      if [[ "$compose_status" == "error" ]]; then
        echo "ERROR: Dokploy compose entered error before creating a new deployment record" >&2
        return 3
      fi
      return 2
    fi

    sleep "$interval_seconds"
  done

  echo "ERROR: Dokploy deployment did not reach done before readiness polling" >&2
  echo "compose_id=$compose_id composeStatus=${compose_status:-unknown} deployment_count=${deployment_count:-unknown} new_deployment_ids=${new_deployment_ids:-none}" >&2
  if [[ -n "${rollout_response:-}" ]]; then
    render_dokploy_rollout_summary "$rollout_response" "deployment-rollout-timeout" >&2
  fi
  exit 1
}

deploy_compose() {
  local endpoint="$1"
  local label="$2"
  local deploy_payload

  deploy_payload=$(safe_jq_build --arg id "$COMPOSE_ID" '{composeId: $id}') || exit 1
  dokploy_api_call "POST" "$endpoint" "$deploy_payload" "$deploy_response_file" "$label"
}

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
vault_repair_env="production"
if [[ "$APP_URL" == *"-staging"* ]]; then
  vault_repair_env="staging"
fi
verify_vault_app_token "$current_env" "Dokploy VAULT_APP_TOKEN preflight" 172800 "$vault_repair_env"

new_env="$current_env"
new_env=$(update_env_var "$new_env" "IMAGE_TAG" "$IMAGE_TAG")
new_env=$(update_env_var "$new_env" "GIT_COMMIT_SHA" "$IMAGE_TAG")
new_env=$(update_env_var "$new_env" "NEXT_PUBLIC_APP_URL" "$APP_URL")
new_env=$(update_env_var "$new_env" "COMPOSE_PROFILES" "app")
new_env=$(update_env_var "$new_env" "TRAEFIK_ENABLE" "true")
new_env=$(update_env_var "$new_env" "IAC_CONFIG_HASH" "deploy-${IMAGE_TAG}-$(date +%s)")
IAC_CONFIG_HASH_VALUE=$(env_value "$new_env" "IAC_CONFIG_HASH")

if [[ -n "${DEPLOY_PRIMARY_MODEL_OVERRIDE:-}" ]]; then
  new_env=$(update_env_var "$new_env" "PRIMARY_MODEL" "$DEPLOY_PRIMARY_MODEL_OVERRIDE")
fi

if [[ -n "${DEPLOY_OCR_MODEL_OVERRIDE:-}" ]]; then
  new_env=$(update_env_var "$new_env" "OCR_MODEL" "$DEPLOY_OCR_MODEL_OVERRIDE")
fi

if [[ -n "${DEPLOY_VISION_MODEL_OVERRIDE:-}" ]]; then
  new_env=$(update_env_var "$new_env" "VISION_MODEL" "$DEPLOY_VISION_MODEL_OVERRIDE")
fi

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

expected_effective_env=$(printf "%s\n" \
  "IMAGE_TAG=$IMAGE_TAG" \
  "GIT_COMMIT_SHA=$IMAGE_TAG" \
  "IAC_CONFIG_HASH=$IAC_CONFIG_HASH_VALUE" \
  "ENV_SUFFIX=$(env_value "$new_env" "ENV_SUFFIX")" \
  "COMPOSE_PROFILES=app")

payload=$(safe_jq_build --arg id "$COMPOSE_ID" --arg env "$new_env" '{composeId: $id, env: $env}') || exit 1
dokploy_api_call "POST" "compose.update" "$payload" "$update_response_file" "Environment update"

echo "Environment updated to use image tag: $IMAGE_TAG"

dokploy_api_call "GET" "compose.one?composeId=$COMPOSE_ID" "" "$response_file" "Effective environment verification"
effective_response=$(cat "$response_file")
effective_env=$(safe_jq '.env // empty' "$effective_response" "effective environment fetch") || exit 1
previous_deployment_ids=$(deployment_ids_from_response "$effective_response") || exit 1
previous_deployment_signatures=$(deployment_signature_map_from_response "$effective_response") || exit 1
render_allowlisted_env_diff "$expected_effective_env" "$effective_env" || {
  echo "ERROR: Effective Dokploy environment does not match expected deployment values" >&2
  exit 1
}

deploy_compose "compose.deploy" "Deployment trigger"
set +e
wait_for_dokploy_deployment_rollout "$COMPOSE_ID" "$previous_deployment_ids" "$previous_deployment_signatures"
rollout_status=$?
set -e

if [[ "$rollout_status" -eq 2 || "$rollout_status" -eq 3 ]]; then
  echo "Initial Dokploy deploy did not create a deployment record; retrying with compose.redeploy"
  dokploy_api_call "GET" "compose.one?composeId=$COMPOSE_ID" "" "$response_file" "Pre-redeploy deployment snapshot"
  redeploy_response=$(cat "$response_file")
  previous_deployment_ids=$(deployment_ids_from_response "$redeploy_response") || exit 1
  previous_deployment_signatures=$(deployment_signature_map_from_response "$redeploy_response") || exit 1
  deploy_compose "compose.redeploy" "Redeployment trigger"
  set +e
  wait_for_dokploy_deployment_rollout "$COMPOSE_ID" "$previous_deployment_ids" "$previous_deployment_signatures"
  rollout_status=$?
  set -e
  if [[ "$rollout_status" -eq 2 ]]; then
    echo "Dokploy redeploy did not expose a new deployment record" >&2
    exit "$rollout_status"
  elif [[ "$rollout_status" -eq 3 ]]; then
    echo "Dokploy redeploy left compose in error without a new deployment record" >&2
    exit "$rollout_status"
  elif [[ "$rollout_status" -ne 0 ]]; then
    exit "$rollout_status"
  fi
elif [[ "$rollout_status" -ne 0 ]]; then
  exit "$rollout_status"
fi

echo "Deployment triggered successfully"
exit 0

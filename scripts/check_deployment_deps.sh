#!/usr/bin/env bash
# Deployment Dependencies Checker
#
# Validates all required environment variables and tools for deployment
# Run this before any deployment steps to catch issues early
#
# Usage:
#   ./scripts/check_deployment_deps.sh [--env-only]
#
# Options:
#   --env-only    Only check environment variables, skip tool checks
#
# Exit codes:
#   0 - All dependencies satisfied
#   1 - Missing dependencies

set -euo pipefail

# shellcheck source=scripts/lib/common.sh
source "$(dirname "$0")/lib/common.sh"

ENV_ONLY=false
[[ "${1:-}" == "--env-only" ]] && ENV_ONLY=true

missing_envs=()
missing_tools=()

for var in DOKPLOY_API_KEY DOKPLOY_API_URL; do
  if ! validate_non_empty "${!var:-}" "$var" 2>/dev/null; then
    missing_envs+=("$var")
  fi
done

if [[ "$ENV_ONLY" == false ]]; then
  command -v curl >/dev/null 2>&1 || missing_tools+=("curl")
  command -v jq >/dev/null 2>&1 || missing_tools+=("jq")
fi

if [[ ${#missing_envs[@]} -gt 0 ]] || [[ ${#missing_tools[@]} -gt 0 ]]; then
  echo "========================================="
  echo "ERROR: Missing Deployment Dependencies"
  echo "========================================="
  
  if [[ ${#missing_envs[@]} -gt 0 ]]; then
    echo ""
    echo "Missing Environment Variables:"
    printf '  ❌ %s\n' "${missing_envs[@]}"
    echo ""
    echo "Fix: Add to workflow step 'env:' section"
    echo "Example:"
    echo "  env:"
    echo "    DOKPLOY_API_KEY: \${{ secrets.DOKPLOY_API_KEY }}"
    echo "    DOKPLOY_API_URL: \${{ env.DOKPLOY_API_URL }}"
  fi
  
  if [[ ${#missing_tools[@]} -gt 0 ]]; then
    echo ""
    echo "Missing Tools:"
    printf '  ❌ %s\n' "${missing_tools[@]}"
    echo ""
    echo "Fix: Install in workflow before deployment"
    echo "  apt-get install -y curl jq"
  fi
  
  echo "========================================="
  exit 1
fi

echo "✅ All deployment dependencies satisfied"
exit 0

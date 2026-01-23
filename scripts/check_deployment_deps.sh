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

ENV_ONLY=false
if [ "${1:-}" = "--env-only" ]; then
  ENV_ONLY=true
fi

missing_envs=()
missing_tools=()

# Check required environment variables
[ -z "${DOKPLOY_API_KEY:-}" ] && missing_envs+=("DOKPLOY_API_KEY")
[ -z "${DOKPLOY_API_URL:-}" ] && missing_envs+=("DOKPLOY_API_URL")

# Check required tools (skip if --env-only)
if [ "$ENV_ONLY" = false ]; then
  command -v curl >/dev/null 2>&1 || missing_tools+=("curl")
  command -v jq >/dev/null 2>&1 || missing_tools+=("jq")
fi

# Report all missing dependencies
if [ ${#missing_envs[@]} -gt 0 ] || [ ${#missing_tools[@]} -gt 0 ]; then
  echo "========================================="
  echo "ERROR: Missing Deployment Dependencies"
  echo "========================================="
  
  if [ ${#missing_envs[@]} -gt 0 ]; then
    echo ""
    echo "Missing Environment Variables:"
    for env in "${missing_envs[@]}"; do
      echo "  ❌ $env"
    done
    echo ""
    echo "Fix: Add to workflow step 'env:' section"
    echo "Example:"
    echo "  env:"
    echo "    DOKPLOY_API_KEY: \${{ secrets.DOKPLOY_API_KEY }}"
    echo "    DOKPLOY_API_URL: \${{ env.DOKPLOY_API_URL }}"
  fi
  
  if [ ${#missing_tools[@]} -gt 0 ]; then
    echo ""
    echo "Missing Tools:"
    for tool in "${missing_tools[@]}"; do
      echo "  ❌ $tool"
    done
    echo ""
    echo "Fix: Install in workflow before deployment"
    echo "  apt-get install -y curl jq"
  fi
  
  echo "========================================="
  exit 1
fi

echo "✅ All deployment dependencies satisfied"
exit 0

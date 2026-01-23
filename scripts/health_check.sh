#!/usr/bin/env bash
# Health Check Script - Unified health check logic for all environments
#
# Usage:
#   ./scripts/health_check.sh <health_url> <environment> [max_attempts] [image_tag]
#
# Arguments:
#   health_url      - Full URL to health endpoint (e.g., https://report.zitian.party/api/health)
#   environment     - Environment name (production, staging, pr-123)
#   max_attempts    - Maximum retry attempts (default: 24)
#   image_tag       - Optional image tag for success message
#
# Exit codes:
#   0 - Health check passed
#   1 - Health check failed (connection error, HTTP error, or unhealthy status)

set -euo pipefail

missing_args=()

HEALTH_URL="${1:-}"
ENVIRONMENT="${2:-}"
MAX_ATTEMPTS="${3:-24}"
IMAGE_TAG="${4:-}"

[ -z "$HEALTH_URL" ] && missing_args+=("health_url")
[ -z "$ENVIRONMENT" ] && missing_args+=("environment")

if [ ${#missing_args[@]} -gt 0 ]; then
  echo "========================================="
  echo "ERROR: Missing Required Arguments"
  echo "========================================="
  echo ""
  for arg in "${missing_args[@]}"; do
    echo "  - $arg"
  done
  echo ""
  echo "Usage: $0 <health_url> <environment> [max_attempts] [image_tag]"
  echo "========================================="
  exit 1
fi

# Extract domain from URL for troubleshooting messages
DOMAIN=$(echo "$HEALTH_URL" | sed -E 's|https?://([^/]+).*|\1|')

# Setup temp files for response/error capture
HEALTH_RESPONSE_FILE=$(mktemp)
HEALTH_ERROR_FILE=$(mktemp)
trap 'rm -f "$HEALTH_RESPONSE_FILE" "$HEALTH_ERROR_FILE"' EXIT INT TERM

echo "Starting health check for $ENVIRONMENT environment"
echo "URL: $HEALTH_URL"
echo "Max attempts: $MAX_ATTEMPTS (timeout: $((MAX_ATTEMPTS * 10))s)"
echo ""

attempt=1

while (( attempt <= MAX_ATTEMPTS )); do
  echo "[WAITING] Health check attempt $attempt/$MAX_ATTEMPTS..."
  
  # Capture both HTTP status code and response body
  http_code=$(curl -s -o "$HEALTH_RESPONSE_FILE" -w "%{http_code}" "$HEALTH_URL" 2>"$HEALTH_ERROR_FILE" || echo "000")
  
  # Check for connection errors (curl exit code != 0)
  if [ "$http_code" = "000" ]; then
    echo "[WARNING] Connection failed (attempt $attempt/$MAX_ATTEMPTS)"
    
    if (( attempt == MAX_ATTEMPTS )); then
      timeout=$((MAX_ATTEMPTS * 10))
      echo ""
      echo "========================================="
      echo "[FAIL] Deployment Failed: Cannot connect to health endpoint"
      echo "========================================="
      echo "URL: $HEALTH_URL"
      echo ""
      echo "Connection error:"
      cat "$HEALTH_ERROR_FILE" 2>/dev/null || echo "(no error details)"
      echo ""
      echo "Troubleshooting:"
      echo "1. Check DNS resolution: nslookup $DOMAIN"
      echo "2. Check TLS certificate: curl -v $HEALTH_URL"
      echo "3. Check container status via Dokploy"
      echo "4. Check SigNoz: https://signoz.zitian.party"
      echo "   Filter: deployment.environment=$ENVIRONMENT service_name=finance-report-backend"
      echo "========================================="
      exit 1
    fi
    
    sleep 10
    ((attempt++))
    continue
  fi
  
  # Check for HTTP errors
  if [ "$http_code" != "200" ]; then
    echo "[WARNING] HTTP $http_code (attempt $attempt/$MAX_ATTEMPTS)"
    
    if (( attempt == MAX_ATTEMPTS )); then
      timeout=$((MAX_ATTEMPTS * 10))
      echo ""
      echo "========================================="
      echo "[FAIL] Deployment Failed: Health endpoint returned HTTP $http_code"
      echo "========================================="
      echo "URL: $HEALTH_URL"
      echo "Response:"
      cat "$HEALTH_RESPONSE_FILE" 2>/dev/null || echo "(no response body)"
      echo ""
      echo "Troubleshooting: Check SigNoz for application logs"
      echo "========================================="
      exit 1
    fi
    
    sleep 10
    ((attempt++))
    continue
  fi
  
  # Check if response contains "healthy"
  health_response=$(cat "$HEALTH_RESPONSE_FILE" 2>/dev/null || echo "")
  if echo "$health_response" | grep -q '"status":"healthy"'; then
    elapsed=$((attempt * 10))
    echo ""
    echo "========================================="
    echo "[SUCCESS] Deployment Successful ($elapsed seconds)"
    echo "========================================="
    if [ -n "$IMAGE_TAG" ]; then
      echo "Version: $IMAGE_TAG"
    fi
    echo "Environment: $ENVIRONMENT"
    echo "URL: ${HEALTH_URL%/api/health}"
    echo "Response: $health_response"
    echo ""
    echo "Logs: https://signoz.zitian.party"
    echo "Filter: deployment.environment=$ENVIRONMENT service_name=finance-report-backend"
    echo "========================================="
    exit 0
  fi
  
  # Response is 200 but not healthy
  echo "[WARNING] Backend is unhealthy (attempt $attempt/$MAX_ATTEMPTS)"
  echo "Response: $health_response"
  
  if (( attempt == MAX_ATTEMPTS )); then
    timeout=$((MAX_ATTEMPTS * 10))
    echo ""
    echo "========================================="
    echo "[FAIL] Deployment Failed: Backend unhealthy after ${timeout}s"
    echo "========================================="
    echo "Last health check response:"
    echo "$health_response"
    echo ""
    echo "Troubleshooting:"
    echo "1. Check which dependency failed in response above"
    echo "2. Check SigNoz: https://signoz.zitian.party"
    echo "   Filter: deployment.environment=$ENVIRONMENT service_name=finance-report-backend"
    echo "3. Look for CHECKPOINT markers in logs:"
    echo "   - [CHECKPOINT-1] Vault secrets not ready"
    echo "   - [CHECKPOINT-2] Database migration failed"
    echo "   - [CHECKPOINT-3] Application startup failed"
    echo "========================================="
    exit 1
  fi
  
  sleep 10
  ((attempt++))
done

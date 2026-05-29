#!/usr/bin/env bash
# Check whether an immutable GHCR image tag already exists.
#
# Usage:
#   tools/check_ghcr_image_tag.sh <image>
#
# Outputs:
#   build_required=true|false is written to $GITHUB_OUTPUT when available.

set -euo pipefail

IMAGE="${1:-}"

if [[ -z "$IMAGE" ]]; then
  echo "Usage: $0 <image>" >&2
  exit 2
fi

write_output() {
  local key="$1"
  local value="$2"

  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf '%s=%s\n' "$key" "$value" >> "$GITHUB_OUTPUT"
  fi
}

if docker buildx imagetools inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Found reusable image: $IMAGE"
  write_output "build_required" "false"
  exit 0
fi

echo "Reusable image not found: $IMAGE"
echo "A fresh build is required."
write_output "build_required" "true"

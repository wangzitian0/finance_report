#!/usr/bin/env bash
# Local infrastructure command implementation for tools/infra.sh.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

# Local infrastructure is for dev/test, not a long-lived service. Default the
# compose restart policy to "no" so postgres/minio do NOT auto-resurrect on the
# next podman start and quietly accumulate as background services (the root
# cause of local podman heat/leak across worktree clones). Override with
# RESTART_POLICY=unless-stopped for an intentionally persistent local stack;
# prod/staging set RESTART_POLICY explicitly in their own deploy env.
: "${RESTART_POLICY:=no}"
export RESTART_POLICY

usage() {
  cat <<'EOF'
Usage: tools/infra.sh [up|down|logs|foreground]

Commands:
  up, docker-up          Start local infrastructure containers in the background.
  down, docker-down      Stop local infrastructure containers and remove the compose network.
  logs, docker-logs      Follow local infrastructure logs.
  foreground            Start infrastructure in the foreground.

Set CONTAINER_RUNTIME=docker or CONTAINER_RUNTIME=podman to force a runtime.
EOF
}

detect_runtime() {
  local requested
  requested="${CONTAINER_RUNTIME:-}"
  requested="$(printf '%s' "$requested" | tr '[:upper:]' '[:lower:]')"

  if [[ -n "$requested" ]]; then
    if [[ "$requested" != "docker" && "$requested" != "podman" ]]; then
      echo "ERROR: CONTAINER_RUNTIME must be either 'docker' or 'podman'." >&2
      exit 1
    fi
    if command -v "$requested" >/dev/null 2>&1; then
      printf '%s\n' "$requested"
      return
    fi
    echo "ERROR: CONTAINER_RUNTIME=$requested not found in PATH." >&2
    exit 1
  fi

  if command -v podman >/dev/null 2>&1; then
    printf '%s\n' podman
    return
  fi
  if command -v docker >/dev/null 2>&1; then
    printf '%s\n' docker
    return
  fi

  echo "ERROR: Neither 'podman' nor 'docker' found in PATH." >&2
  exit 1
}

command_name="${1:-up}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "$command_name" in
  up | docker-up | foreground | down | docker-down | logs | docker-logs)
    ;;
  -h | --help | help)
    usage
    exit 0
    ;;
  *)
    echo "ERROR: Unknown infra command: $command_name" >&2
    usage >&2
    exit 2
    ;;
esac

runtime="$(detect_runtime)"
compose=("$runtime" compose -f "$REPO_ROOT/docker-compose.yml")

case "$command_name" in
  up | docker-up)
    echo "Starting local infrastructure with $runtime compose..."
    exec "${compose[@]}" --profile infra up -d "$@"
    ;;
  foreground)
    echo "Starting local infrastructure in the foreground with $runtime compose..."
    exec "${compose[@]}" --profile infra up postgres minio minio-init "$@"
    ;;
  down | docker-down)
    echo "Stopping local infrastructure with $runtime compose..."
    exec "${compose[@]}" down "$@"
    ;;
  logs | docker-logs)
    exec "${compose[@]}" logs -f "$@"
    ;;
esac

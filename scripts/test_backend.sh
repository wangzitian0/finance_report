#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="${COMPOSE_FILE:-$repo_root/docker-compose.yml}"
# Use per-user cache directory to avoid security issues with world-writable /tmp
state_dir="${XDG_CACHE_HOME:-$HOME/.cache}/finance_report"
mkdir -p "$state_dir"
chmod 700 "$state_dir"
branch_name="${BRANCH_NAME:-}"
if [ -z "$branch_name" ] && command -v git >/dev/null 2>&1; then
  branch_name="$(git -C "$repo_root" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [ "$branch_name" = "HEAD" ]; then
    branch_name=""
  fi
fi

safe_branch=""
if [ -n "$branch_name" ]; then
  safe_branch="$(printf '%s' "$branch_name" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9._-]/-/g' | sed 's/^-*//; s/-*$//')"
fi

workspace_id="${WORKSPACE_ID:-}"
if [ -z "$workspace_id" ] && command -v cksum >/dev/null 2>&1; then
  workspace_id="$(printf '%s' "$repo_root" | cksum | awk '{print $1}')"
  if [ "${#workspace_id}" -gt 8 ]; then
    workspace_id="${workspace_id: -8}"
  fi
fi

env_suffix=""
if [ -n "$safe_branch" ] && [ -n "$workspace_id" ]; then
  env_suffix="-$safe_branch-$workspace_id"
elif [ -n "$safe_branch" ]; then
  env_suffix="-$safe_branch"
elif [ -n "$workspace_id" ]; then
  env_suffix="-$workspace_id"
fi

lock_key="${safe_branch:-default}"
if [ -n "$workspace_id" ]; then
  lock_key="${lock_key}-${workspace_id}"
fi
lock_dir="${state_dir}/db-${lock_key}.lock"
state_file="${state_dir}/db-${lock_key}.state"

compose_project="finance-report"
if [ -n "$env_suffix" ]; then
  compose_project="finance-report${env_suffix}"
fi

compose_cmd=()
runtime_cmd=()
db_container_name="finance-report-db${env_suffix}"

if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
  compose_cmd=(podman compose)
  runtime_cmd=(podman)
elif command -v podman-compose >/dev/null 2>&1; then
  compose_cmd=(podman-compose)
  runtime_cmd=(podman)
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  compose_cmd=(docker compose)
  runtime_cmd=(docker)
elif command -v docker-compose >/dev/null 2>&1; then
  compose_cmd=(docker-compose)
  runtime_cmd=(docker)
else
  echo "No compose command found (podman compose/podman-compose/docker compose/docker-compose)." >&2
  exit 1
fi

is_db_running() {
  "${runtime_cmd[@]}" ps --filter "name=${db_container_name}" --filter "status=running" --format "{{.Names}}" \
    | grep -q "^${db_container_name}$"
}

get_db_container_id() {
  "${runtime_cmd[@]}" ps -a --filter "name=${db_container_name}" --format "{{.ID}}" | head -n 1
}

get_db_host_port() {
  "${runtime_cmd[@]}" port "$db_container_name" 5432/tcp 2>/dev/null | head -n 1 | awk -F: '{print $NF}'
}

compose() {
  env COMPOSE_PROJECT_NAME="$compose_project" ENV_SUFFIX="$env_suffix" POSTGRES_PORT="${POSTGRES_PORT:-5432}" \
    "${compose_cmd[@]}" "$@"
}

db_exec() {
  "${runtime_cmd[@]}" exec -i "$db_container_name" "$@"
}

acquire_lock() {
  local attempts=30
  while ! mkdir "$lock_dir" 2>/dev/null; do
    if [ -f "$lock_dir/pid" ]; then
      local lock_pid
      lock_pid="$(cat "$lock_dir/pid" 2>/dev/null || true)"
      if [ -n "$lock_pid" ] && ! ps -p "$lock_pid" >/dev/null 2>&1; then
        rm -rf "$lock_dir"
        continue
      fi
    fi
    attempts=$((attempts - 1))
    if [ "$attempts" -le 0 ]; then
      echo "Unable to acquire lock for ${db_container_name}." >&2
      exit 1
    fi
    sleep 1
  done
  echo "$$" > "$lock_dir/pid"
}

release_lock() {
  rm -rf "$lock_dir"
}

write_state() {
  cat > "$state_file" <<EOF
managed=$1
started_existing=$2
refcount=$3
container_id=$4
db_port=$5
EOF
}

# Parse state file as data (not sourcing) to prevent code injection
read_state() {
  managed="$(grep '^managed=' "$state_file" 2>/dev/null | cut -d= -f2 || echo false)"
  started_existing="$(grep '^started_existing=' "$state_file" 2>/dev/null | cut -d= -f2 || echo false)"
  refcount="$(grep '^refcount=' "$state_file" 2>/dev/null | cut -d= -f2 || echo 0)"
  container_id="$(grep '^container_id=' "$state_file" 2>/dev/null | cut -d= -f2 || echo '')"
  db_port="$(grep '^db_port=' "$state_file" 2>/dev/null | cut -d= -f2 || echo '')"
}

cleanup() {
  # Kill only direct child processes of THIS script (safe for multi-window)
  # This catches pytest and any subprocesses it spawned
  pkill -P $$ 2>/dev/null || true
  
  acquire_lock
  if [ -f "$state_file" ]; then
    read_state
    managed="${managed:-false}"
    started_existing="${started_existing:-false}"
    refcount="${refcount:-0}"
    container_id="${container_id:-}"
    if [ "$refcount" -gt 0 ]; then
      refcount=$((refcount - 1))
    fi
    if [ "$refcount" -le 0 ]; then
      current_id="$(get_db_container_id || true)"
      if [ -n "$container_id" ] && [ "$current_id" = "$container_id" ]; then
        if [ "$managed" = "true" ]; then
          "${runtime_cmd[@]}" rm -f "$container_id" >/dev/null 2>&1 || true
          if ! "${runtime_cmd[@]}" volume rm "${compose_project}_postgres_data" >/dev/null 2>&1; then
            echo "Warning: failed to remove volume ${compose_project}_postgres_data; clean up manually if needed." >&2
          fi
        elif [ "$started_existing" = "true" ]; then
          if ! "${runtime_cmd[@]}" stop "$db_container_name" >/dev/null 2>&1; then
            echo "Warning: failed to stop ${db_container_name}; leaving state for manual cleanup." >&2
            write_state "$managed" "$started_existing" 1 "$container_id" "${db_port:-}"
            release_lock
            return
          fi
        fi
      fi
      rm -f "$state_file"
      # NOTE: We do NOT pkill playwright globally - it may belong to other test sessions
      # pytest handles its own playwright cleanup; if orphaned, user can manually clean
    else
      write_state "$managed" "$started_existing" "$refcount" "$container_id" "${db_port:-5432}"
    fi
  fi
  release_lock
}
trap cleanup EXIT

acquire_lock
managed="false"
started_existing="false"

if [ -f "$state_file" ] && [ -z "${POSTGRES_PORT:-}" ]; then
  read_state
  if [ -n "${db_port:-}" ]; then
    POSTGRES_PORT="$db_port"
  fi
fi

if [ -z "${POSTGRES_PORT:-}" ] && [ -n "$env_suffix" ]; then
  if command -v cksum >/dev/null 2>&1; then
    # Derive a deterministic Postgres port in the range 5400-5999 from env_suffix.
    port_seed="$(printf '%s' "$env_suffix" | cksum | awk '{print $1}')"
    POSTGRES_PORT=$((5400 + (port_seed % 600)))
  else
    POSTGRES_PORT=5432
  fi
fi
if [ -z "${POSTGRES_PORT:-}" ]; then
  POSTGRES_PORT=5432
fi
export POSTGRES_PORT

if is_db_running; then
  container_id="$(get_db_container_id || true)"
  if [ -f "$state_file" ]; then
    read_state
    refcount="${refcount:-0}"
    refcount=$((refcount + 1))
    write_state "$managed" "$started_existing" "$refcount" "$container_id" "${db_port:-${POSTGRES_PORT:-5432}}"
  else
    host_port="$(get_db_host_port || true)"
    if [ -n "$host_port" ]; then
      POSTGRES_PORT="$host_port"
    fi
    write_state "false" "false" 1 "$container_id" "${POSTGRES_PORT:-5432}"
  fi
else
  container_id="$(get_db_container_id || true)"
  if [ -n "$container_id" ]; then
    started_existing="true"
    if ! "${runtime_cmd[@]}" start "$db_container_name"; then
      echo "Failed to start existing Postgres container '${db_container_name}'." >&2
      release_lock
      exit 1
    fi
  else
    managed="true"
    compose -f "$compose_file" up -d postgres
  fi
  host_port="$(get_db_host_port || true)"
  if [ -n "$host_port" ]; then
    if [ -n "${POSTGRES_PORT:-}" ] && [ "$POSTGRES_PORT" != "$host_port" ]; then
      echo "Warning: ${db_container_name} is bound to port ${host_port}, overriding ${POSTGRES_PORT}." >&2
    fi
    POSTGRES_PORT="$host_port"
  else
    echo "Failed to detect host port mapping for ${db_container_name}." >&2
    release_lock
    exit 1
  fi
  container_id="$(get_db_container_id || true)"
  write_state "$managed" "$started_existing" 1 "$container_id" "${POSTGRES_PORT:-5432}"
fi
release_lock

for _ in {1..30}; do
  if db_exec pg_isready -U postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! db_exec pg_isready -U postgres >/dev/null 2>&1; then
  echo "PostgreSQL is not ready after waiting 30 seconds on port ${POSTGRES_PORT:-5432}." >&2
  exit 1
fi

if ! db_exec psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname='finance_report_test'" | grep -q 1; then
  db_exec psql -U postgres -c "CREATE DATABASE finance_report_test;"
fi

export TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:${POSTGRES_PORT:-5432}/finance_report_test"
export S3_ACCESS_KEY="minio"
export S3_SECRET_KEY="minio123"

cd "$repo_root/apps/backend"
uv run pytest "$@"

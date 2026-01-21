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
  safe_branch="$(printf '%s' "$branch_name" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9._\\-]/-/g' | sed 's/^-*//; s/-*$//')"
  if [ -z "$safe_branch" ]; then
    safe_branch="unnamed"
  fi
fi

workspace_id="${WORKSPACE_ID:-}"
if [ -z "$workspace_id" ] && command -v cksum >/dev/null 2>&1; then
  workspace_id="$(printf '%s' "$repo_root" | cksum | awk '{print $1}')"
  if [ "${#workspace_id}" -gt 8 ]; then
    workspace_id="${workspace_id#"${workspace_id%????????}"}"
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
tunnel_pid=""

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
  local output status
  set +e
  output="$("${runtime_cmd[@]}" port "$db_container_name" 5432/tcp 2>&1)"
  status=$?
  set -e
  if [ "$status" -ne 0 ]; then
    case "$output" in
      *"No public port"*|*"not published"*|*"no such port"*)
        return 0
        ;;
      *)
        echo "Error: failed to get port mapping for ${db_container_name}: ${output}" >&2
        return "$status"
        ;;
    esac
  fi
  printf '%s\n' "$output" | head -n 1 | awk -F: '{print $NF}'
}

get_db_container_ip() {
  "${runtime_cmd[@]}" inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$db_container_name" \
    | tr -d '[:space:]'
}

wait_for_db_host_port() {
  local host_port=""
  for _ in {1..30}; do
    host_port="$(get_db_host_port || true)"
    if [ -n "$host_port" ]; then
      break
    fi
    sleep 1
  done
  printf '%s' "$host_port"
}

get_podman_machine_name() {
  local name
  name="$(podman machine list --format "{{.Name}} {{.Running}}" 2>/dev/null | awk '$2=="true"{print $1; exit}')"
  name="${name%\*}"
  printf '%s' "$name"
}

start_podman_tunnel() {
  local target_host="$1"
  local local_port="$2"
  local machine
  machine="$(get_podman_machine_name)"
  if [ -z "$machine" ]; then
    echo "No running podman machine found for SSH tunnel." >&2
    return 1
  fi
  local ssh_identity ssh_port ssh_user
  ssh_identity="$(podman machine inspect "$machine" --format '{{.SSHConfig.IdentityPath}}' 2>/dev/null || true)"
  ssh_port="$(podman machine inspect "$machine" --format '{{.SSHConfig.Port}}' 2>/dev/null || true)"
  ssh_user="$(podman machine inspect "$machine" --format '{{.SSHConfig.RemoteUsername}}' 2>/dev/null || true)"
  if [ -z "$ssh_identity" ] || [ -z "$ssh_port" ] || [ -z "$ssh_user" ]; then
    echo "Failed to resolve podman machine SSH config for ${machine}." >&2
    return 1
  fi
  ssh -i "$ssh_identity" -p "$ssh_port" \
    -o ExitOnForwardFailure=yes \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -N -L "127.0.0.1:${local_port}:${target_host}:5432" \
    "${ssh_user}@localhost" >/dev/null 2>&1 &
  tunnel_pid=$!
  for _ in {1..10}; do
    if python - <<PY >/dev/null 2>&1
import socket
s = socket.socket()
s.settimeout(0.5)
try:
    s.connect(("127.0.0.1", int("${local_port}")))
    s.close()
    raise SystemExit(0)
except OSError:
    raise SystemExit(1)
PY
    then
      return 0
    fi
    if ! kill -0 "$tunnel_pid" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  echo "Failed to establish SSH tunnel to ${target_host}:5432 via podman machine." >&2
  return 1
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
  local managed_value="$1"
  local started_existing_value="$2"
  local refcount_value="$3"
  local container_id_value="$4"
  local db_port_value="$5"
  local db_host_value="${6:-localhost}"
  cat > "$state_file" <<EOF
managed=$managed_value
started_existing=$started_existing_value
refcount=$refcount_value
container_id=$container_id_value
db_port=$db_port_value
db_host=$db_host_value
EOF
}

# Parse state file as data (not sourcing) to prevent code injection
read_state() {
  managed="$(grep '^managed=' "$state_file" 2>/dev/null | cut -d= -f2 || echo false)"
  started_existing="$(grep '^started_existing=' "$state_file" 2>/dev/null | cut -d= -f2 || echo false)"
  refcount="$(grep '^refcount=' "$state_file" 2>/dev/null | cut -d= -f2 || echo 0)"
  container_id="$(grep '^container_id=' "$state_file" 2>/dev/null | cut -d= -f2 || echo '')"
  db_port="$(grep '^db_port=' "$state_file" 2>/dev/null | cut -d= -f2 || echo '')"
  db_host="$(grep '^db_host=' "$state_file" 2>/dev/null | cut -d= -f2 || echo '')"
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
        # managed=true and started_existing=true are mutually exclusive by design.
        if [ "$managed" = "true" ]; then
          db_data_volumes="$("${runtime_cmd[@]}" inspect -f '{{range .Mounts}}{{if or (eq .Destination "/var/lib/postgresql/data") (eq .Destination "/var/lib/postgres/data")}}{{.Name}} {{end}}{{end}}' "$container_id" 2>/dev/null || true)"
          "${runtime_cmd[@]}" rm -f "$container_id" >/dev/null 2>&1 || true
          if [ -n "${db_data_volumes:-}" ]; then
            for volume_name in $db_data_volumes; do
              if [ -n "$volume_name" ]; then
                if ! "${runtime_cmd[@]}" volume rm "$volume_name" >/dev/null 2>&1; then
                  echo "Warning: failed to remove volume ${volume_name}; clean up manually if needed." >&2
                fi
              fi
            done
          else
            if ! "${runtime_cmd[@]}" volume rm "${compose_project}_postgres_data" >/dev/null 2>&1; then
              echo "Warning: failed to remove volume ${compose_project}_postgres_data; clean up manually if needed." >&2
            fi
          fi
        elif [ "$started_existing" = "true" ]; then
          if ! "${runtime_cmd[@]}" stop "$db_container_name" >/dev/null 2>&1; then
            echo "Warning: failed to stop ${db_container_name}; leaving state for manual cleanup." >&2
            write_state "$managed" "$started_existing" "$((refcount + 1))" "$container_id" "${db_port:-}"
            release_lock
            return
          fi
        fi
      fi
      rm -f "$state_file"
      # NOTE: We do NOT pkill playwright globally - it may belong to other test sessions
      # pytest handles its own playwright cleanup; if orphaned, user can manually clean
    else
      write_state "$managed" "$started_existing" "$refcount" "$container_id" "${db_port:-5432}" "${db_host:-localhost}"
    fi
  fi
  release_lock
  if [ -n "${tunnel_pid:-}" ]; then
    kill "$tunnel_pid" >/dev/null 2>&1 || true
  fi
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
  if [ -n "${db_host:-}" ] && [ "$db_host" != "localhost" ] && [ "${runtime_cmd[0]}" = "podman" ]; then
    POSTGRES_PORT="${POSTGRES_PORT:-5432}"
    tunnel_target="$db_host"
    if [ "$tunnel_target" = "127.0.0.1" ]; then
      tunnel_target="$(get_db_container_ip || true)"
    fi
    if [ -z "$tunnel_target" ]; then
      tunnel_target="$db_container_name"
    fi
    if ! start_podman_tunnel "$tunnel_target" "$POSTGRES_PORT"; then
      exit 1
    fi
    db_host="127.0.0.1"
  fi
fi
db_host="${db_host:-localhost}"

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
    db_host="${db_host:-localhost}"
    if [ "$db_host" = "localhost" ]; then
      host_port="$(get_db_host_port || true)"
      if [ -n "$host_port" ]; then
        POSTGRES_PORT="$host_port"
      else
        db_host="$(get_db_container_ip)"
        if [ -z "$db_host" ]; then
          echo "Failed to detect container IP for ${db_container_name}." >&2
          release_lock
          exit 1
        fi
        if [ "${runtime_cmd[0]}" = "podman" ]; then
          POSTGRES_PORT="${POSTGRES_PORT:-5432}"
          if ! start_podman_tunnel "$db_host" "$POSTGRES_PORT"; then
            release_lock
            exit 1
          fi
          db_host="127.0.0.1"
        else
          POSTGRES_PORT=5432
        fi
      fi
    fi
    write_state "$managed" "$started_existing" "$refcount" "$container_id" "${POSTGRES_PORT:-5432}" "$db_host"
  else
    host_port="$(wait_for_db_host_port)"
    if [ -n "$host_port" ]; then
      POSTGRES_PORT="$host_port"
      db_host="localhost"
    else
      db_host="$(get_db_container_ip)"
      if [ -z "$db_host" ]; then
        echo "Failed to detect host port mapping or container IP for ${db_container_name}." >&2
        release_lock
        exit 1
      fi
      if [ "${runtime_cmd[0]}" = "podman" ]; then
        POSTGRES_PORT="${POSTGRES_PORT:-5432}"
        if ! start_podman_tunnel "$db_host" "$POSTGRES_PORT"; then
          release_lock
          exit 1
        fi
        db_host="127.0.0.1"
      else
        POSTGRES_PORT=5432
      fi
    fi
    write_state "false" "false" 1 "$container_id" "${POSTGRES_PORT:-5432}" "$db_host"
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
  host_port="$(wait_for_db_host_port)"
  if [ -n "$host_port" ]; then
    if [ -n "${POSTGRES_PORT:-}" ] && [ "$POSTGRES_PORT" != "$host_port" ]; then
      echo "Warning: ${db_container_name} is bound to port ${host_port}, overriding ${POSTGRES_PORT}." >&2
    fi
    POSTGRES_PORT="$host_port"
    db_host="localhost"
  else
    if [ "${runtime_cmd[0]}" = "podman" ]; then
      POSTGRES_PORT="${POSTGRES_PORT:-5432}"
      db_host="$(get_db_container_ip)"
      if [ -z "$db_host" ]; then
        echo "Failed to detect container IP for ${db_container_name}." >&2
        release_lock
        exit 1
      fi
      if ! start_podman_tunnel "$db_host" "$POSTGRES_PORT"; then
        release_lock
        exit 1
      fi
      db_host="127.0.0.1"
    else
      db_host="$(get_db_container_ip)"
      if [ -z "$db_host" ]; then
        echo "Failed to detect host port mapping or container IP for ${db_container_name}." >&2
        release_lock
        exit 1
      fi
      POSTGRES_PORT=5432
    fi
  fi
  container_id="$(get_db_container_id || true)"
  write_state "$managed" "$started_existing" 1 "$container_id" "${POSTGRES_PORT:-5432}" "$db_host"
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

export TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@${db_host}:${POSTGRES_PORT:-5432}/finance_report_test"
export S3_ACCESS_KEY="minio"
export S3_SECRET_KEY="minio123"

# Ensure test database is migrated to the latest schema (prevents Test vs Prod drift)
echo "Running database migrations on test database..."
uv run alembic upgrade head -x dburl="$TEST_DATABASE_URL"

cd "$repo_root/apps/backend"
uv run pytest "$@"

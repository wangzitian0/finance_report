#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="${COMPOSE_FILE:-$repo_root/docker-compose.ci.yml}"
# Use per-user cache directory to avoid security issues with world-writable /tmp
state_dir="${XDG_CACHE_HOME:-$HOME/.cache}/finance_report"
mkdir -p "$state_dir"
chmod 700 "$state_dir"
lock_dir="${state_dir}/db.lock"
state_file="${state_dir}/db.state"

compose_cmd=()
runtime_cmd=()

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
  "${runtime_cmd[@]}" ps --filter "name=finance_report_db" --filter "status=running" --format "{{.Names}}" \
    | grep -q "^finance_report_db$"
}

get_db_container_id() {
  "${runtime_cmd[@]}" ps -a --filter "name=finance_report_db" --format "{{.ID}}" | head -n 1
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
      echo "Unable to acquire lock for finance_report_db." >&2
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
managed=true
refcount=$1
container_id=$2
EOF
}

# Parse state file as data (not sourcing) to prevent code injection
read_state() {
  refcount="$(grep '^refcount=' "$state_file" 2>/dev/null | cut -d= -f2 || echo 0)"
  container_id="$(grep '^container_id=' "$state_file" 2>/dev/null | cut -d= -f2 || echo '')"
}

cleanup() {
  # Kill only direct child processes of THIS script (safe for multi-window)
  # This catches pytest and any subprocesses it spawned
  pkill -P $$ 2>/dev/null || true
  
  acquire_lock
  if [ -f "$state_file" ]; then
    read_state
    refcount="${refcount:-0}"
    container_id="${container_id:-}"
    if [ "$refcount" -gt 0 ]; then
      refcount=$((refcount - 1))
    fi
    if [ "$refcount" -le 0 ]; then
      current_id="$(get_db_container_id || true)"
      if [ -n "$container_id" ] && [ "$current_id" = "$container_id" ]; then
        "${runtime_cmd[@]}" rm -f "$container_id" >/dev/null 2>&1 || true
      fi
      rm -f "$state_file"
      # NOTE: We do NOT pkill playwright globally - it may belong to other test sessions
      # pytest handles its own playwright cleanup; if orphaned, user can manually clean
    else
      write_state "$refcount" "$container_id"
    fi
  fi
  release_lock
}
trap cleanup EXIT

acquire_lock
if ! is_db_running; then
  rm -f "$state_file"
  "${compose_cmd[@]}" -f "$compose_file" up -d postgres
  container_id="$(get_db_container_id || true)"
  write_state 1 "$container_id"
elif [ -f "$state_file" ]; then
  read_state
  refcount="${refcount:-0}"
  container_id="${container_id:-}"
  refcount=$((refcount + 1))
  write_state "$refcount" "$container_id"
fi
release_lock

exec_tty_flag=("-T")
if ! "${compose_cmd[@]}" -f "$compose_file" exec -T postgres true >/dev/null 2>&1; then
  exec_tty_flag=()
fi

for _ in {1..30}; do
  if "${compose_cmd[@]}" -f "$compose_file" exec ${exec_tty_flag[@]+"${exec_tty_flag[@]}"} postgres pg_isready -U postgres \
    >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! "${compose_cmd[@]}" -f "$compose_file" exec ${exec_tty_flag[@]+"${exec_tty_flag[@]}"} postgres psql -U postgres -tc \
  "SELECT 1 FROM pg_database WHERE datname='finance_report_test'" | grep -q 1; then
  "${compose_cmd[@]}" -f "$compose_file" exec ${exec_tty_flag[@]+"${exec_tty_flag[@]}"} postgres psql -U postgres -c \
    "CREATE DATABASE finance_report_test;"
fi

export TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report_test"

cd "$repo_root/apps/backend"
uv run pytest "$@"

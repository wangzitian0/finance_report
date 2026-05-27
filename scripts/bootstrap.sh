#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

LOCAL_BIN="${HOME}/.local/bin"
NVM_VERSION="0.40.3"
mkdir -p "$LOCAL_BIN"
export PATH="${LOCAL_BIN}:${PATH}"

log() {
  printf '\n[%s] %s\n' "bootstrap" "$*"
}

warn() {
  printf '\n[bootstrap] WARNING: %s\n' "$*" >&2
}

die() {
  printf '\n[bootstrap] ERROR: %s\n' "$*" >&2
  exit 1
}

runtime_version() {
  local key="$1"
  awk -v key="$key" '
    /^\[runtime\]/ { in_runtime = 1; next }
    /^\[/ { in_runtime = 0 }
    in_runtime && $1 == key {
      gsub(/"/, "", $3)
      print $3
      exit
    }
  ' toolchain.toml
}

PYTHON_VERSION="$(runtime_version python)"
NODE_VERSION="$(runtime_version node)"
UV_VERSION="$(runtime_version uv)"

require_command() {
  local name="$1"
  local install_hint="$2"
  if ! command -v "$name" >/dev/null 2>&1; then
    die "$name is not available. ${install_hint}"
  fi
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1 && [ "$(uv --version)" = "uv ${UV_VERSION}" ]; then
    log "uv ${UV_VERSION} already available"
    return
  fi

  require_command curl "Install curl, then rerun: bash scripts/bootstrap.sh"
  log "Installing uv ${UV_VERSION}"
  local installer
  installer="$(mktemp)"
  curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" -o "$installer"
  sh "$installer"
  rm -f "$installer"
  export PATH="${LOCAL_BIN}:${PATH}"
}

ensure_python() {
  log "Installing Python ${PYTHON_VERSION} with uv"
  uv python install "$PYTHON_VERSION"

  local python_target
  python_target="$(uv python find "$PYTHON_VERSION")"

  if command -v python >/dev/null 2>&1 && [ "$(python --version 2>&1)" = "Python ${PYTHON_VERSION}" ]; then
    log "python resolves to ${PYTHON_VERSION}"
    return
  fi

  if [ ! -e "${LOCAL_BIN}/python" ] || [ -L "${LOCAL_BIN}/python" ]; then
    ln -sfn "$python_target" "${LOCAL_BIN}/python"
    log "Linked ${LOCAL_BIN}/python to Python ${PYTHON_VERSION}"
    return
  fi

  warn "Not replacing existing ${LOCAL_BIN}/python. Moon tasks use python3; backend venv is pinned with uv."
}

load_nvm() {
  export NVM_DIR="${NVM_DIR:-${HOME}/.nvm}"
  if [ -s "${NVM_DIR}/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "${NVM_DIR}/nvm.sh"
  fi
}

ensure_nvm() {
  load_nvm
  if type nvm >/dev/null 2>&1; then
    return
  fi

  require_command curl "Install curl, then rerun: bash scripts/bootstrap.sh"
  log "Installing nvm ${NVM_VERSION}"
  local installer
  installer="$(mktemp)"
  curl -LsSf "https://raw.githubusercontent.com/nvm-sh/nvm/v${NVM_VERSION}/install.sh" -o "$installer"
  bash "$installer"
  rm -f "$installer"
  load_nvm
  type nvm >/dev/null 2>&1 || die "nvm installation did not load. Restart the shell and rerun bootstrap."
}

ensure_node() {
  ensure_nvm
  log "Installing Node.js ${NODE_VERSION} with nvm"
  nvm install "$NODE_VERSION"
  nvm use "$NODE_VERSION"
  export PATH="${NVM_DIR}/versions/node/v${NODE_VERSION}/bin:${PATH}"
}

ensure_moon() {
  local moon_bin="${NVM_DIR}/versions/node/v${NODE_VERSION}/bin/moon"
  if [ -x "$moon_bin" ]; then
    log "Moon CLI already available for Node ${NODE_VERSION}"
    return
  fi

  log "Installing Moon CLI for Node ${NODE_VERSION}"
  npm install -g @moonrepo/cli
}

install_project_dependencies() {
  log "Installing project dependencies through Moon"
  moon run :setup
}

install_pre_commit() {
  log "Installing pre-commit hooks"
  uvx pre-commit install
}

check_container_runtime() {
  if command -v podman >/dev/null 2>&1; then
    log "Container runtime detected: $(podman --version)"
    return
  fi

  if command -v docker >/dev/null 2>&1; then
    log "Container runtime detected: $(docker --version)"
    return
  fi

  warn "No container runtime found. Install Docker Desktop with WSL integration or Podman before running backend/full tests, dev infra, or smoke tests."
}

main() {
  log "Bootstrapping Finance Report"
  ensure_uv
  ensure_python
  ensure_node
  ensure_moon
  install_project_dependencies
  install_pre_commit
  check_container_runtime

  log "Done. Next command: moon run :dev"
}

main "$@"

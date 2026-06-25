#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

LOCAL_BIN="${HOME}/.local/bin"
export NVM_DIR="${NVM_DIR:-${HOME}/.nvm}"
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

detect_host_environment() {
  local kernel
  kernel="$(uname -s 2>/dev/null || printf 'unknown')"

  case "$kernel" in
    MINGW* | MSYS* | CYGWIN*)
      printf 'windows-bash'
      return
      ;;
    Darwin)
      printf 'macos'
      return
      ;;
  esac

  if [ -n "${WSL_DISTRO_NAME:-}" ]; then
    printf 'wsl'
    return
  fi

  if [ -r /proc/sys/kernel/osrelease ] && grep -qi microsoft /proc/sys/kernel/osrelease; then
    printf 'wsl'
    return
  fi

  case "$kernel" in
    Linux)
      printf 'linux'
      ;;
    *)
      printf 'unknown'
      ;;
  esac
}

configure_host_environment() {
  local host_environment
  host_environment="${FINANCE_REPORT_HOST_ENV:-$(detect_host_environment)}"

  case "$host_environment" in
    wsl)
      log "Execution environment: WSL Ubuntu (${WSL_DISTRO_NAME:-unknown distro})"
      export PATH="${LOCAL_BIN}:/usr/local/bin:/usr/bin:/bin:${PATH}"
      ;;
    macos)
      log "Execution environment: macOS POSIX shell"
      export PATH="${LOCAL_BIN}:${PATH}"
      ;;
    linux)
      log "Execution environment: Linux POSIX shell"
      export PATH="${LOCAL_BIN}:/usr/local/bin:/usr/bin:/bin:${PATH}"
      ;;
    windows-bash)
      die "This bootstrap must run in WSL Ubuntu, macOS Terminal, or a Linux shell. Windows PowerShell, Git Bash, MSYS, Cygwin, and Scoop paths do not share WSL tools or Python packages. From Windows PowerShell, run: wsl.exe -d Ubuntu --cd /home/<user>/workspace/finance_report --exec /bin/bash -lc \"bash tools/bootstrap.sh\""
      ;;
    *)
      warn "Unknown execution environment. Continuing with explicit PATH setup; prefer WSL Ubuntu, macOS Terminal, or a Linux shell."
      export PATH="${LOCAL_BIN}:${PATH}"
      ;;
  esac

  if [ -d "${NVM_DIR}/versions/node/v${NODE_VERSION}/bin" ]; then
    export PATH="${NVM_DIR}/versions/node/v${NODE_VERSION}/bin:${PATH}"
  fi
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1 && [ "$(uv --version)" = "uv ${UV_VERSION}" ]; then
    log "uv ${UV_VERSION} already available"
    return
  fi

  require_command curl "Install curl, then rerun: bash tools/bootstrap.sh"
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

  require_command curl "Install curl, then rerun: bash tools/bootstrap.sh"
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

retire_legacy_pre_push_hook() {
  # Make the pre-commit framework the single owner of git hooks. Two things on a
  # developer machine can shadow it: (1) a hand-placed native pre-push hook (e.g.
  # an old full-pytest script) that pre-commit preserves and keeps running as
  # `.legacy`; (2) a redundant `core.hooksPath` override, which makes
  # `pre-commit install` "cowardly refuse". Both are retired here so the managed
  # pre-commit + pre-push drift gates (`.pre-commit-config.yaml`) actually run.
  local git_dir hooks_path default_hooks pre_push
  git_dir="$(git rev-parse --git-dir 2>/dev/null || printf '.git')"
  default_hooks="$(cd "$git_dir" 2>/dev/null && pwd)/hooks"

  hooks_path="$(git config --local --get core.hooksPath 2>/dev/null || true)"
  if [ -n "$hooks_path" ]; then
    local resolved
    resolved="$(cd "$hooks_path" 2>/dev/null && pwd || printf '%s' "$hooks_path")"
    if [ "$resolved" = "$default_hooks" ]; then
      log "Unsetting redundant core.hooksPath ($hooks_path) so pre-commit can install"
      git config --local --unset core.hooksPath || true
    else
      warn "core.hooksPath points outside the repo ($hooks_path); leaving it. If pre-commit refuses to install, unset it manually."
    fi
  fi

  pre_push="${git_dir}/hooks/pre-push"
  if [ -f "$pre_push" ] && ! grep -q "pre-commit" "$pre_push" 2>/dev/null; then
    log "Retiring orphan native pre-push hook -> ${pre_push}.legacy.bak"
    mv "$pre_push" "${pre_push}.legacy.bak"
  fi
}

install_pre_commit() {
  log "Installing pre-commit hooks"
  retire_legacy_pre_push_hook
  uvx pre-commit install
}

check_optional_tool() {
  local name="$1"
  local purpose="$2"

  if command -v "$name" >/dev/null 2>&1; then
    log "${name} detected for ${purpose}: $(command -v "$name")"
    return
  fi

  warn "${name} not found for ${purpose}. Install it in this execution environment; PATH and package installations are not shared between WSL Ubuntu, macOS/Linux shells, and Windows PowerShell/Scoop."
}

check_optional_agent_tools() {
  log "Checking optional developer and agent tools"
  check_optional_tool gh "GitHub PR and CI operations"
  check_optional_tool jq "JSON shell processing"
  check_optional_tool yq "YAML shell processing"
  check_optional_tool direnv "per-directory environment variables"
  check_optional_tool op "1Password CLI secrets access"
}

check_container_runtime() {
  if command -v podman >/dev/null 2>&1; then
    if podman compose version >/dev/null 2>&1; then
      log "Container runtime detected: $(podman --version)"
      return
    fi
    warn "podman is installed, but 'podman compose' is not available in this execution environment."
  fi

  if command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
      log "Container runtime detected: $(docker --version)"
      return
    fi
    warn "docker is installed, but 'docker compose' is not available in this execution environment."
  fi

  warn "No container runtime found. Install Docker Desktop with WSL integration or Podman before running backend/full tests, dev infra, or smoke tests."
}

main() {
  log "Bootstrapping Finance Report"
  configure_host_environment
  check_optional_agent_tools
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

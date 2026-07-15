"""Shared developer-command access to the repository toolchain contract."""

from __future__ import annotations

import os
import shutil
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def get_runtime_version(name: str) -> str:
    """Read a runtime version from the repository toolchain contract."""
    with (REPO_ROOT / "toolchain.toml").open("rb") as fh:
        toolchain = tomllib.load(fh)
    return str(toolchain["runtime"][name])


def uv_run(*args: str) -> list[str]:
    """Build a uv command pinned to the SSOT Python runtime."""
    return ["uv", "run", "--python", get_runtime_version("python"), *args]


def get_container_runtime() -> str | None:
    """Resolve the requested or first available container runtime."""
    requested = os.environ.get("CONTAINER_RUNTIME", "").strip().lower()
    if requested:
        if requested not in {"podman", "docker"}:
            print(
                "ERROR: CONTAINER_RUNTIME must be either 'podman' or 'docker'",
                file=sys.stderr,
            )
            return None
        if shutil.which(requested):
            return requested
        print(
            f"ERROR: CONTAINER_RUNTIME={requested} not found in PATH", file=sys.stderr
        )
        return None

    if shutil.which("podman"):
        return "podman"
    if shutil.which("docker"):
        return "docker"
    return None


def get_compose_cmd() -> list[str]:
    """Return the env-aware container runtime's compose command."""
    runtime = get_container_runtime()
    if runtime is None:
        if not os.environ.get("CONTAINER_RUNTIME", "").strip():
            print("ERROR: Neither podman nor docker found in PATH", file=sys.stderr)
        raise SystemExit(1)
    return [runtime, "compose"]

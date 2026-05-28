#!/usr/bin/env python3
"""Validate local, CI, and container runtime version declarations."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path


def load_toolchain(repo_root: Path) -> dict:
    with (repo_root / "toolchain.toml").open("rb") as fh:
        return tomllib.load(fh)


def read_text(repo_root: Path, relative_path: str) -> str:
    return (repo_root / relative_path).read_text(encoding="utf-8")


def expect_equal(errors: list[str], label: str, actual: str, expected: str) -> None:
    if actual.strip() != expected:
        errors.append(f"{label}: expected {expected!r}, got {actual.strip()!r}")


def expect_contains(errors: list[str], path: str, haystack: str, needle: str) -> None:
    if needle not in haystack:
        errors.append(f"{path}: missing {needle!r}")


def check_tool_files(repo_root: Path, toolchain: dict, errors: list[str]) -> None:
    python_version = toolchain["runtime"]["python"]
    node_version = toolchain["runtime"]["node"]

    expect_equal(
        errors,
        ".python-version",
        read_text(repo_root, ".python-version"),
        python_version,
    )
    expect_equal(
        errors, ".node-version", read_text(repo_root, ".node-version"), node_version
    )
    expect_equal(errors, ".nvmrc", read_text(repo_root, ".nvmrc"), node_version)

    tool_versions = read_text(repo_root, ".tool-versions")
    expect_contains(errors, ".tool-versions", tool_versions, f"python {python_version}")
    expect_contains(errors, ".tool-versions", tool_versions, f"nodejs {node_version}")
    expect_contains(
        errors, ".tool-versions", tool_versions, f"uv {toolchain['runtime']['uv']}"
    )

    npmrc = read_text(repo_root, ".npmrc")
    expect_contains(errors, ".npmrc", npmrc, "engine-strict=true")


def check_frontend_package(repo_root: Path, toolchain: dict, errors: list[str]) -> None:
    package = json.loads(read_text(repo_root, "apps/frontend/package.json"))
    expected_node = toolchain["runtime"]["node"]
    actual_node = package.get("engines", {}).get("node")
    if actual_node != expected_node:
        errors.append(
            "apps/frontend/package.json: engines.node must match "
            f"toolchain.toml runtime.node ({expected_node!r}), got {actual_node!r}"
        )


def check_moon_toolchain(repo_root: Path, toolchain: dict, errors: list[str]) -> None:
    node_version = toolchain["runtime"]["node"]
    npm_version = toolchain["runtime"]["npm"]
    moon_toolchain = read_text(repo_root, ".moon/toolchain.yml")

    for needle in (
        "packageManager: npm",
        f"version: '{node_version}'",
        f"version: '{npm_version}'",
    ):
        expect_contains(errors, ".moon/toolchain.yml", moon_toolchain, needle)


def check_workflows(repo_root: Path, toolchain: dict, errors: list[str]) -> None:
    python_version = toolchain["runtime"]["python"]
    node_version = toolchain["runtime"]["node"]
    uv_version = toolchain["runtime"]["uv"]
    postgres_image = toolchain["images"]["postgres"]

    workflow_expectations = {
        ".github/workflows/ci.yml": (
            f'PYTHON_VERSION: "{python_version}"',
            f'NODE_VERSION: "{node_version}"',
            f'UV_VERSION: "{uv_version}"',
            f"image: {postgres_image}",
            "python-version: ${{ env.PYTHON_VERSION }}",
            "node-version: ${{ env.NODE_VERSION }}",
            "version: ${{ env.UV_VERSION }}",
            "python tools/ci/check_toolchain_contract.py",
        ),
        ".github/workflows/staging-deploy.yml": (
            f'PYTHON_VERSION: "{python_version}"',
            f'UV_VERSION: "{uv_version}"',
            "python-version: ${{ env.PYTHON_VERSION }}",
            "version: ${{ env.UV_VERSION }}",
        ),
        ".github/workflows/production-release.yml": (
            f'PYTHON_VERSION: "{python_version}"',
            f'UV_VERSION: "{uv_version}"',
            "python-version: ${{ env.PYTHON_VERSION }}",
            "version: ${{ env.UV_VERSION }}",
        ),
        ".github/workflows/docs.yml": (
            f'PYTHON_VERSION: "{python_version}"',
            "python-version: ${{ env.PYTHON_VERSION }}",
        ),
        ".github/actions/setup-e2e-tests/action.yml": (
            f'version: "{uv_version}"',
            "python-version-file: .python-version",
        ),
    }
    for path, needles in workflow_expectations.items():
        content = read_text(repo_root, path)
        for needle in needles:
            expect_contains(errors, path, content, needle)


def check_container_files(repo_root: Path, toolchain: dict, errors: list[str]) -> None:
    images = toolchain["images"]

    backend = read_text(repo_root, "apps/backend/Dockerfile")
    for needle in (
        f"ARG PYTHON_IMAGE={images['backend_python']}",
        f"ARG UV_IMAGE={images['backend_uv']}",
        "FROM ${UV_IMAGE} AS uv-source",
        "FROM ${PYTHON_IMAGE} AS builder",
        "COPY --from=uv-source /uv /usr/local/bin/uv",
        "FROM ${PYTHON_IMAGE}",
    ):
        expect_contains(errors, "apps/backend/Dockerfile", backend, needle)

    frontend = read_text(repo_root, "apps/frontend/Dockerfile")
    for needle in (
        f"ARG NODE_IMAGE={images['frontend_node']}",
        "FROM ${NODE_IMAGE} AS builder",
        "FROM ${NODE_IMAGE}",
    ):
        expect_contains(errors, "apps/frontend/Dockerfile", frontend, needle)

    compose = read_text(repo_root, "docker-compose.yml")
    for image in (
        images["postgres"],
        images["minio"],
        images["minio_client"],
    ):
        expect_contains(errors, "docker-compose.yml", compose, f"image: {image}")

    for key, image in (
        ("PYTHON_IMAGE", images["backend_python"]),
        ("UV_IMAGE", images["backend_uv"]),
        ("NODE_IMAGE", images["frontend_node"]),
    ):
        expect_contains(errors, "docker-compose.yml", compose, f"${{{key}:-{image}}}")


def run_contract(repo_root: Path) -> int:
    errors: list[str] = []
    toolchain = load_toolchain(repo_root)
    check_tool_files(repo_root, toolchain, errors)
    check_frontend_package(repo_root, toolchain, errors)
    check_moon_toolchain(repo_root, toolchain, errors)
    check_workflows(repo_root, toolchain, errors)
    check_container_files(repo_root, toolchain, errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Toolchain contract OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args()
    return run_contract(args.repo_root)


if __name__ == "__main__":
    raise SystemExit(main())

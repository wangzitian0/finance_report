#!/usr/bin/env python3
"""Validate local, CI, and container runtime version declarations."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import tomllib

from common.meta.base.gate_cli import run_gate


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


def expect_image(errors: list[str], path: str, content: str, image: str) -> None:
    """Match a complete literal Compose image, allowing quotes/comments/spacing."""
    pattern = (
        rf"(?m)^\s*image:\s*(?P<quote>['\"]?){re.escape(image)}"
        r"(?P=quote)[ \t]*(?:#.*)?$"
    )
    if not re.search(pattern, content):
        errors.append(f"{path}: missing governed image {image!r}")


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
    from common.runtime.generate_workflows import project_all

    status, proj_errors, _ = project_all(repo_root, check_only=True)
    if status != 0:
        errors.extend(proj_errors)

    ci_path = ".github/workflows/ci.yml"
    try:
        ci_content = read_text(repo_root, ci_path)
    except FileNotFoundError:
        errors.append(f"{ci_path}: file not found")
        return
    for job_name in ("backend-integration", "backend-e2e-tier1"):
        job_pattern = (
            rf"(?m)^\s\s{re.escape(job_name)}:\s*$(.*?)(?=^\s\s\w[\w-]*:\s*$|\Z)"
        )
        match = re.search(job_pattern, ci_content, re.DOTALL)
        if match:
            job_body = match.group(1)
            if job_body.count("./.github/actions/setup-minio") < 2:
                errors.append(
                    f"{ci_path}: job {job_name} must invoke ./.github/actions/setup-minio (start and wait)"
                )
        else:
            errors.append(f"{ci_path}: job {job_name} not found")

    minio_steps = [
        block
        for block in re.split(r"(?m)^\s*- (?=(?:name|id|run|uses):)", ci_content)
        if "docker run" in block
        and ("MINIO_ROOT_USER" in block or "mc alias set" in block)
    ]
    for index, block in enumerate(minio_steps, start=1):
        block_lines = [
            line for line in block.splitlines() if not line.lstrip().startswith("#")
        ]
        for key in ("minio", "minio_client"):
            image = toolchain["images"][key]
            if not any(image in line for line in block_lines):
                errors.append(
                    f"{ci_path}: MinIO acquisition step {index} must use {key}={image!r}"
                )


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
        expect_image(errors, "docker-compose.yml", compose, image)

    preview_path = "docker-compose.pr-preview.yml"
    preview = read_text(repo_root, preview_path)
    for key in ("minio", "minio_client"):
        expect_image(errors, preview_path, preview, images[key])

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


def _run_command(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args(argv)
    return run_contract(args.repo_root)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        status = _run_command(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if status == 2:
        return 2
    findings = [] if status == 0 else [f"command returned status {status}"]
    return run_gate(
        "TOOLCHAIN-CONTRACT", lambda _repo_root: findings, [], failure_status=status
    )


if __name__ == "__main__":
    raise SystemExit(main())

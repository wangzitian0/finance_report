#!/usr/bin/env python3
"""Validate local, CI, and container runtime version declarations."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import tomllib

from common.meta.base.gate_cli import run_gate


def _project_env_header(
    content: str,
    python_version: str | None = None,
    node_version: str | None = None,
    uv_version: str | None = None,
) -> str:
    """Project PYTHON_VERSION, NODE_VERSION, UV_VERSION in top-level env: block."""
    if python_version is not None:
        content, count = re.subn(
            r'(?m)^(\s*PYTHON_VERSION:\s*)[\x27"][^\x27"]+[\x27"]',
            r"\g<1>" + f'"{python_version}"',
            content,
        )
        if count == 0:
            raise ValueError("missing required PYTHON_VERSION pin in env block")
    if node_version is not None:
        content, count = re.subn(
            r'(?m)^(\s*NODE_VERSION:\s*)[\x27"][^\x27"]+[\x27"]',
            r"\g<1>" + f'"{node_version}"',
            content,
        )
        if count == 0:
            raise ValueError("missing required NODE_VERSION pin in env block")
    if uv_version is not None:
        content, count = re.subn(
            r'(?m)^(\s*UV_VERSION:\s*)[\x27"][^\x27"]+[\x27"]',
            r"\g<1>" + f'"{uv_version}"',
            content,
        )
        if count == 0:
            raise ValueError("missing required UV_VERSION pin in env block")
    return content


def _project_ci_workflow(content: str, toolchain: dict) -> str:
    """Project ci.yml env headers and service container pins."""
    runtime = toolchain["runtime"]
    images = toolchain["images"]
    content = _project_env_header(
        content,
        python_version=runtime.get("python"),
        node_version=runtime.get("node"),
        uv_version=runtime.get("uv"),
    )
    postgres_img = images["postgres"]
    content, count = re.subn(
        r"(?m)^(\s*postgres:\s*\n\s*image:\s*)[\S]+",
        r"\g<1>" + postgres_img,
        content,
    )
    if count == 0:
        raise ValueError("missing required postgres service image pin in ci.yml")
    return content


def _project_docs_workflow(content: str, toolchain: dict) -> str:
    """Project docs.yml env headers."""
    runtime = toolchain["runtime"]
    return _project_env_header(
        content,
        python_version=runtime.get("python"),
    )


def _project_setup_minio_action(content: str, toolchain: dict) -> str:
    """Project MinIO container images into setup-minio composite action."""
    images = toolchain["images"]
    minio_img = images["minio"]
    minio_client_img = images["minio_client"]

    lines = content.splitlines(keepends=True)
    server_updated = False
    client_updated = False
    new_lines = []
    for i, line in enumerate(lines):
        if i + 1 < len(lines) and "server /data" in lines[i + 1]:
            m = re.match(
                r"^([ \t]*)[\x22\x27]?([^\s\\\x22\x27]+)[\x22\x27]?([ \t]*\\\s*)$",
                line,
            )
            if m:
                indent, cur_img, suffix = m.groups()
                if cur_img != minio_img:
                    line = f"{indent}{minio_img}{suffix}"
                server_updated = True
        elif "--entrypoint /bin/sh" in line:
            m = re.match(
                r"^([ \t]*docker run [^\n]*?--entrypoint /bin/sh[ \t]+)[\x22\x27]?([^\s\\\x22\x27]+)[\x22\x27]?([ \t]*\\\s*)$",
                line,
            )
            if m:
                prefix, cur_img, suffix = m.groups()
                if cur_img != minio_client_img:
                    line = f"{prefix}{minio_client_img}{suffix}"
                client_updated = True
        new_lines.append(line)

    if not server_updated:
        raise ValueError(
            "missing required minio server image pin in setup-minio/action.yml"
        )
    if not client_updated:
        raise ValueError(
            "missing required minio-client image pin in setup-minio/action.yml"
        )

    return "".join(new_lines)


def _project_setup_e2e_tests_action(content: str, toolchain: dict) -> str:
    """Project uv version into setup-e2e-tests composite action."""
    uv_version = toolchain["runtime"]["uv"]
    lines = content.splitlines(keepends=True)
    in_install_uv = False
    updated = False
    new_lines = []
    for line in lines:
        if re.match(r"^[ \t]*-[ \t]*name:[ \t]*['\"]?Install uv['\"]?", line):
            in_install_uv = True
        elif in_install_uv and re.match(r"^[ \t]*-", line):
            in_install_uv = False
        elif in_install_uv and re.match(
            r"^[ \t]*version:[ \t]*['\"][^'\"]+['\"]", line
        ):
            line = re.sub(
                r"^([ \t]*version:[ \t]*)['\"][^'\"]+['\"]",
                r"\g<1>" + f'"{uv_version}"',
                line,
            )
            updated = True
            in_install_uv = False
        new_lines.append(line)
    if not updated:
        raise ValueError(
            "missing required Install uv version pin in setup-e2e-tests/action.yml"
        )
    return "".join(new_lines)


def _project_setup_backend_env_action(content: str, toolchain: dict) -> str:
    """Project default uv and python versions into setup-backend-env composite action."""
    runtime = toolchain["runtime"]
    uv_version = runtime["uv"]
    python_version = runtime["python"]
    lines = content.splitlines(keepends=True)
    new_lines = []
    current_input = None
    uv_updated = False
    py_updated = False
    for line in lines:
        m_input = re.match(r"^[ \t]{2}([a-zA-Z0-9_-]+):[ \t]*$", line)
        if m_input:
            current_input = m_input.group(1)
        elif re.match(r"^[ \t]{0,1}[a-zA-Z0-9_-]+:", line):
            current_input = None

        if current_input == "uv-version":
            m_def = re.match(r"^([ \t]+default:[ \t]*)['\"][^'\"]+['\"]", line)
            if m_def:
                prefix = m_def.group(1)
                line = f"{prefix}'{uv_version}'\n"
                uv_updated = True
                current_input = None
        elif current_input == "python-version":
            m_def = re.match(r"^([ \t]+default:[ \t]*)['\"][^'\"]+['\"]", line)
            if m_def:
                prefix = m_def.group(1)
                line = f"{prefix}'{python_version}'\n"
                py_updated = True
                current_input = None
        new_lines.append(line)

    if not uv_updated:
        raise ValueError(
            "missing required uv-version default in setup-backend-env/action.yml"
        )
    if not py_updated:
        raise ValueError(
            "missing required python-version default in setup-backend-env/action.yml"
        )

    return "".join(new_lines)


def _project_compose(content: str, toolchain: dict) -> str:
    """Project service images and ARG defaults into docker-compose files."""
    images = toolchain["images"]
    lines = content.splitlines(keepends=True)
    new_lines = []
    current_service = None
    counts = {"postgres": 0, "minio": 0, "minio-init": 0}

    for line in lines:
        service_match = re.match(r"^([ \t]{2})([a-zA-Z0-9_-]+):[ \t]*(?:#.*)?$", line)
        if service_match:
            current_service = service_match.group(2)
        elif re.match(r"^[ \t]{0,1}[a-zA-Z0-9_-]+:", line):
            current_service = None

        if current_service in counts:
            img_match = re.match(
                r"^([ \t]{4}image:[ \t]*)[\x22\x27]?([^\s#\x22\x27]+)[\x22\x27]?([ \t]*(?:#.*)?\n?)$",
                line,
            )
            if img_match:
                prefix, cur_img, suffix = img_match.groups()
                target_key = (
                    "postgres"
                    if current_service == "postgres"
                    else ("minio" if current_service == "minio" else "minio_client")
                )
                target_img = images[target_key]
                if cur_img != target_img:
                    line = f"{prefix}{target_img}{suffix}"
                counts[current_service] += 1
                current_service = None

        new_lines.append(line)

    for svc, cnt in counts.items():
        if cnt == 0:
            raise ValueError(f"missing required {svc} image pin in compose file")

    res = "".join(new_lines)
    node_img = images.get("frontend_node")
    if node_img:
        res, cnt = re.subn(
            r"\$\{NODE_IMAGE:-[^}]+}", f"${{NODE_IMAGE:-{node_img}}}", res
        )
        if cnt == 0:
            raise ValueError("missing required NODE_IMAGE default in compose file")
    uv_img = images.get("backend_uv")
    if uv_img:
        res, cnt = re.subn(r"\$\{UV_IMAGE:-[^}]+}", f"${{UV_IMAGE:-{uv_img}}}", res)
        if cnt == 0:
            raise ValueError("missing required UV_IMAGE default in compose file")
    py_img = images.get("backend_python")
    if py_img:
        res, cnt = re.subn(
            r"\$\{PYTHON_IMAGE:-[^}]+}", f"${{PYTHON_IMAGE:-{py_img}}}", res
        )
        if cnt == 0:
            raise ValueError("missing required PYTHON_IMAGE default in compose file")
    return res


def _project_backend_dockerfile(content: str, toolchain: dict) -> str:
    """Project base images into backend Dockerfile."""
    images = toolchain["images"]
    content, py_count = re.subn(
        r"(?m)^ARG PYTHON_IMAGE=.*$",
        f"ARG PYTHON_IMAGE={images['backend_python']}",
        content,
    )
    if py_count == 0:
        raise ValueError("missing required ARG PYTHON_IMAGE in apps/backend/Dockerfile")
    content, uv_count = re.subn(
        r"(?m)^ARG UV_IMAGE=.*$",
        f"ARG UV_IMAGE={images['backend_uv']}",
        content,
    )
    if uv_count == 0:
        raise ValueError("missing required ARG UV_IMAGE in apps/backend/Dockerfile")

    backend_stages = (
        "FROM ${UV_IMAGE} AS uv-source",
        "FROM ${PYTHON_IMAGE} AS builder",
        "COPY --from=uv-source /uv /usr/local/bin/uv",
        "FROM ${PYTHON_IMAGE}",
    )
    lines = [line.strip() for line in content.splitlines()]
    for stage in backend_stages:
        if stage not in lines:
            raise ValueError(
                f"missing required stage '{stage}' in apps/backend/Dockerfile"
            )

    return content


def _project_frontend_dockerfile(content: str, toolchain: dict) -> str:
    """Project base node image into frontend Dockerfile."""
    images = toolchain["images"]
    content, count = re.subn(
        r"(?m)^ARG NODE_IMAGE=.*$",
        f"ARG NODE_IMAGE={images['frontend_node']}",
        content,
    )
    if count == 0:
        raise ValueError("missing required ARG NODE_IMAGE in apps/frontend/Dockerfile")

    frontend_stages = (
        "FROM ${NODE_IMAGE} AS builder",
        "FROM ${NODE_IMAGE}",
    )
    lines = [line.strip() for line in content.splitlines()]
    for stage in frontend_stages:
        if stage not in lines:
            raise ValueError(
                f"missing required stage '{stage}' in apps/frontend/Dockerfile"
            )

    return content


PROJECTORS: dict[str, tuple[Callable[[str, dict], str], bool]] = {
    ".github/workflows/ci.yml": (_project_ci_workflow, True),
    ".github/workflows/docs.yml": (_project_docs_workflow, True),
    ".github/actions/setup-minio/action.yml": (_project_setup_minio_action, True),
    ".github/actions/setup-e2e-tests/action.yml": (
        _project_setup_e2e_tests_action,
        True,
    ),
    ".github/actions/setup-backend-env/action.yml": (
        _project_setup_backend_env_action,
        False,
    ),
    "docker-compose.yml": (_project_compose, True),
    "apps/backend/Dockerfile": (_project_backend_dockerfile, True),
    "apps/frontend/Dockerfile": (_project_frontend_dockerfile, True),
}


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
    for rel_path, (projector, is_required) in PROJECTORS.items():
        file_path = repo_root / rel_path
        if not file_path.exists():
            if is_required:
                errors.append(f"{rel_path}: file not found (required)")
            continue
        try:
            original = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{rel_path}: failed to read: {exc}")
            continue
        try:
            projected = projector(original, toolchain)
        except Exception as exc:
            errors.append(f"{rel_path}: projection error: {exc}")
            continue
        if original != projected:
            diff = "".join(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    projected.splitlines(keepends=True),
                    fromfile=f"{rel_path} (on disk)",
                    tofile=f"{rel_path} (projected from toolchain.toml)",
                )
            )
            errors.append(
                f"{rel_path} has drifted from toolchain.toml projection:\n{diff}"
            )


def run_contract(repo_root: Path) -> int:
    errors: list[str] = []
    toolchain = load_toolchain(repo_root)
    check_tool_files(repo_root, toolchain, errors)
    check_frontend_package(repo_root, toolchain, errors)
    check_moon_toolchain(repo_root, toolchain, errors)
    check_workflows(repo_root, toolchain, errors)

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

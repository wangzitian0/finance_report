#!/usr/bin/env python3
"""Validate local, CI, and container runtime version declarations."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_gate


def _sub_required(pattern: str, repl: str, content: str, error: str) -> str:
    updated, count = re.subn(pattern, repl, content)
    if count == 0:
        raise ValueError(error)
    return updated


def _require_stages(content: str, stages: Sequence[str], dockerfile: str) -> None:
    lines = {line.strip() for line in content.splitlines()}
    for stage in stages:
        if stage not in lines:
            raise ValueError(f"missing required stage '{stage}' in {dockerfile}")


def _project_env_header(
    content: str,
    python_version: str | None = None,
    node_version: str | None = None,
    uv_version: str | None = None,
) -> str:
    for key, val in (
        ("PYTHON_VERSION", python_version),
        ("NODE_VERSION", node_version),
        ("UV_VERSION", uv_version),
    ):
        if val is not None:
            content = _sub_required(
                rf'(?m)^(\s*{key}:\s*)[\x27"][^\x27"]+[\x27"]',
                r"\g<1>" + f'"{val}"',
                content,
                f"missing required {key} pin in env block",
            )
    return content


def _project_ci_workflow(content: str, toolchain: dict) -> str:
    runtime = toolchain["runtime"]
    content = _project_env_header(
        content,
        python_version=runtime.get("python"),
        node_version=runtime.get("node"),
        uv_version=runtime.get("uv"),
    )
    return _sub_required(
        r"(?m)^(\s*postgres:\s*\n\s*image:\s*)[\S]+",
        r"\g<1>" + toolchain["images"]["postgres"],
        content,
        "missing required postgres service image pin in ci.yml",
    )


def _project_docs_workflow(content: str, toolchain: dict) -> str:
    return _project_env_header(
        content, python_version=toolchain["runtime"].get("python")
    )


def _project_setup_minio_action(content: str, toolchain: dict) -> str:
    images = toolchain["images"]
    minio_img, minio_client_img = images["minio"], images["minio_client"]
    lines = content.splitlines(keepends=True)
    server_updated = client_updated = False
    new_lines = []
    for i, line in enumerate(lines):
        if i + 1 < len(lines) and "server /data" in lines[i + 1]:
            if m := re.match(
                r"^([ \t]*)[\x22\x27]?([^\s\\\x22\x27]+)[\x22\x27]?([ \t]*\\\s*)$",
                line,
            ):
                indent, cur_img, suffix = m.groups()
                line = f"{indent}{minio_img}{suffix}" if cur_img != minio_img else line
                server_updated = True
        elif "--entrypoint /bin/sh" in line:
            if m := re.match(
                r"^([ \t]*docker run [^\n]*?--entrypoint /bin/sh[ \t]+)[\x22\x27]?([^\s\\\x22\x27]+)[\x22\x27]?([ \t]*\\\s*)$",
                line,
            ):
                prefix, cur_img, suffix = m.groups()
                line = (
                    f"{prefix}{minio_client_img}{suffix}"
                    if cur_img != minio_client_img
                    else line
                )
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
    uv_version = toolchain["runtime"]["uv"]
    in_install_uv = updated = False
    new_lines = []
    for line in content.splitlines(keepends=True):
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
            updated, in_install_uv = True, False
        new_lines.append(line)
    if not updated:
        raise ValueError(
            "missing required Install uv version pin in setup-e2e-tests/action.yml"
        )
    return "".join(new_lines)


def _project_setup_backend_env_action(content: str, toolchain: dict) -> str:
    runtime = toolchain["runtime"]
    targets = {"uv-version": runtime["uv"], "python-version": runtime["python"]}
    updated: set[str] = set()
    current_input: str | None = None
    new_lines = []
    for line in content.splitlines(keepends=True):
        if m_input := re.match(r"^[ \t]{2}([a-zA-Z0-9_-]+):[ \t]*$", line):
            current_input = m_input.group(1)
        elif re.match(r"^[ \t]{0,1}[a-zA-Z0-9_-]+:", line):
            current_input = None

        if current_input in targets:
            if m_def := re.match(r"^([ \t]+default:[ \t]*)['\"][^'\"]+['\"]", line):
                line = f"{m_def.group(1)}'{targets[current_input]}'\n"
                updated.add(current_input)
                current_input = None
        new_lines.append(line)

    for key in ("uv-version", "python-version"):
        if key not in updated:
            raise ValueError(
                f"missing required {key} default in setup-backend-env/action.yml"
            )
    return "".join(new_lines)


def _project_compose(content: str, toolchain: dict) -> str:
    images = toolchain["images"]
    svc_to_key = {
        "postgres": "postgres",
        "minio": "minio",
        "minio-init": "minio_client",
    }
    counts = dict.fromkeys(svc_to_key, 0)
    current_service: str | None = None
    new_lines = []

    for line in content.splitlines(keepends=True):
        if svc_match := re.match(r"^([ \t]{2})([a-zA-Z0-9_-]+):[ \t]*(?:#.*)?$", line):
            current_service = svc_match.group(2)
        elif re.match(r"^[ \t]{0,1}[a-zA-Z0-9_-]+:", line):
            current_service = None

        if current_service in counts:
            if img_match := re.match(
                r"^([ \t]{4}image:[ \t]*)[\x22\x27]?([^\s#\x22\x27]+)[\x22\x27]?([ \t]*(?:#.*)?\n?)$",
                line,
            ):
                prefix, cur_img, suffix = img_match.groups()
                target_img = images[svc_to_key[current_service]]
                if cur_img != target_img:
                    line = f"{prefix}{target_img}{suffix}"
                counts[current_service] += 1
                current_service = None
        new_lines.append(line)

    for svc, cnt in counts.items():
        if cnt == 0:
            raise ValueError(f"missing required {svc} image pin in compose file")

    res = "".join(new_lines)
    for var_name, img_key in (
        ("NODE_IMAGE", "frontend_node"),
        ("UV_IMAGE", "backend_uv"),
        ("PYTHON_IMAGE", "backend_python"),
    ):
        if img_val := images.get(img_key):
            res = _sub_required(
                rf"\$\{{{var_name}:-[^}}]+}}",
                f"${{{var_name}:-{img_val}}}",
                res,
                f"missing required {var_name} default in compose file",
            )
    return res


def _project_backend_dockerfile(content: str, toolchain: dict) -> str:
    images = toolchain["images"]
    for arg_name, img_key in (
        ("PYTHON_IMAGE", "backend_python"),
        ("UV_IMAGE", "backend_uv"),
    ):
        content = _sub_required(
            rf"(?m)^ARG {arg_name}=.*$",
            f"ARG {arg_name}={images[img_key]}",
            content,
            f"missing required ARG {arg_name} in apps/backend/Dockerfile",
        )
    _require_stages(
        content,
        (
            "FROM ${UV_IMAGE} AS uv-source",
            "FROM ${PYTHON_IMAGE} AS builder",
            "COPY --from=uv-source /uv /usr/local/bin/uv",
            "FROM ${PYTHON_IMAGE}",
        ),
        "apps/backend/Dockerfile",
    )
    return content


def _project_frontend_dockerfile(content: str, toolchain: dict) -> str:
    content = _sub_required(
        r"(?m)^ARG NODE_IMAGE=.*$",
        f"ARG NODE_IMAGE={toolchain['images']['frontend_node']}",
        content,
        "missing required ARG NODE_IMAGE in apps/frontend/Dockerfile",
    )
    _require_stages(
        content,
        ("FROM ${NODE_IMAGE} AS builder", "FROM ${NODE_IMAGE}"),
        "apps/frontend/Dockerfile",
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
    runtime = toolchain["runtime"]
    py_ver, node_ver = runtime["python"], runtime["node"]
    expect_equal(
        errors, ".python-version", read_text(repo_root, ".python-version"), py_ver
    )
    expect_equal(
        errors, ".node-version", read_text(repo_root, ".node-version"), node_ver
    )
    expect_equal(errors, ".nvmrc", read_text(repo_root, ".nvmrc"), node_ver)

    tool_versions = read_text(repo_root, ".tool-versions")
    for needle in (f"python {py_ver}", f"nodejs {node_ver}", f"uv {runtime['uv']}"):
        expect_contains(errors, ".tool-versions", tool_versions, needle)
    expect_contains(
        errors, ".npmrc", read_text(repo_root, ".npmrc"), "engine-strict=true"
    )


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
    runtime = toolchain["runtime"]
    moon_toolchain = read_text(repo_root, ".moon/toolchain.yml")
    for needle in (
        "packageManager: npm",
        f"version: '{runtime['node']}'",
        f"version: '{runtime['npm']}'",
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
    return run_contract(parser.parse_args(argv).repo_root)


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

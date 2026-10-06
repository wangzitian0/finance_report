"""Project toolchain SSOT versions and images into workflows and actions."""

from __future__ import annotations

import argparse
import difflib
import re
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]


def load_toolchain(repo_root: Path) -> dict:
    """Load toolchain.toml from the given repository root."""
    toolchain_path = repo_root / "toolchain.toml"
    with toolchain_path.open("rb") as fh:
        return tomllib.load(fh)


def project_env_header(
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


def project_ci_workflow(content: str, toolchain: dict) -> str:
    """Project ci.yml env headers and service container pins."""
    runtime = toolchain["runtime"]
    images = toolchain["images"]
    content = project_env_header(
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


def project_deploy_workflow(content: str, toolchain: dict) -> str:
    """Project deploy.yml env headers."""
    runtime = toolchain["runtime"]
    return project_env_header(
        content,
        python_version=runtime.get("python"),
        node_version=runtime.get("node"),
        uv_version=runtime.get("uv"),
    )


def project_docs_workflow(content: str, toolchain: dict) -> str:
    """Project docs.yml env headers."""
    runtime = toolchain["runtime"]
    return project_env_header(
        content,
        python_version=runtime.get("python"),
    )


def project_release_workflow(content: str, toolchain: dict) -> str:
    """Project release.yml env headers."""
    runtime = toolchain["runtime"]
    return project_env_header(
        content,
        python_version=runtime.get("python"),
        node_version=runtime.get("node"),
        uv_version=runtime.get("uv"),
    )


def project_deploy_freshness_workflow(content: str, toolchain: dict) -> str:
    """Project deploy-freshness.yml env headers."""
    runtime = toolchain["runtime"]
    return project_env_header(
        content,
        python_version=runtime.get("python"),
    )


def project_benchmark_workflow(content: str, toolchain: dict) -> str:
    """Project benchmark.yml env headers."""
    runtime = toolchain["runtime"]
    return project_env_header(
        content,
        python_version=runtime.get("python"),
        uv_version=runtime.get("uv"),
    )


def project_audit_replay_workflow(content: str, toolchain: dict) -> str:
    """Project python-version into audit-replay.yml."""
    py_version = toolchain["runtime"]["python"]
    lines = content.splitlines(keepends=True)
    new_lines = []
    in_setup_py = False
    updated = False
    for line in lines:
        if re.match(r"^[ \t]*-[ \t]*name:[ \t]*['\"]?Set up Python['\"]?", line):
            in_setup_py = True
        elif in_setup_py and re.match(r"^[ \t]*-", line):
            in_setup_py = False
        elif in_setup_py and re.match(
            r"^[ \t]*python-version:[ \t]*['\"][^'\"]+['\"]", line
        ):
            line = re.sub(
                r"^([ \t]*python-version:[ \t]*)['\"][^'\"]+['\"]",
                r"\g<1>" + f'"{py_version}"',
                line,
            )
            updated = True
            in_setup_py = False
        new_lines.append(line)
    if not updated:
        raise ValueError("missing required python-version in audit-replay.yml")
    return "".join(new_lines)


def project_setup_minio_action(content: str, toolchain: dict) -> str:
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


def project_setup_e2e_tests_action(content: str, toolchain: dict) -> str:
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


def project_setup_backend_env_action(content: str, toolchain: dict) -> str:
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


def project_compose(content: str, toolchain: dict) -> str:
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


def project_backend_dockerfile(content: str, toolchain: dict) -> str:
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


def project_frontend_dockerfile(content: str, toolchain: dict) -> str:
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


# Registry of governed files: relative path -> (projector_function, required_in_repo)
PROJECTORS: dict[str, tuple[Callable[[str, dict], str], bool]] = {
    ".github/workflows/ci.yml": (project_ci_workflow, True),
    ".github/workflows/deploy.yml": (project_deploy_workflow, True),
    ".github/workflows/docs.yml": (project_docs_workflow, True),
    ".github/actions/setup-minio/action.yml": (project_setup_minio_action, True),
    ".github/actions/setup-e2e-tests/action.yml": (
        project_setup_e2e_tests_action,
        True,
    ),
    ".github/workflows/release.yml": (project_release_workflow, False),
    ".github/workflows/deploy-freshness.yml": (
        project_deploy_freshness_workflow,
        False,
    ),
    ".github/workflows/benchmark.yml": (project_benchmark_workflow, False),
    ".github/workflows/audit-replay.yml": (project_audit_replay_workflow, False),
    ".github/actions/setup-backend-env/action.yml": (
        project_setup_backend_env_action,
        False,
    ),
    "docker-compose.yml": (project_compose, True),
    "docker-compose.pr-preview.yml": (project_compose, True),
    "apps/backend/Dockerfile": (project_backend_dockerfile, True),
    "apps/frontend/Dockerfile": (project_frontend_dockerfile, True),
}


def diff_text(label: str, original: str, projected: str) -> str:
    """Generate unified diff between original content and projected content."""
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            projected.splitlines(keepends=True),
            fromfile=f"{label} (on disk)",
            tofile=f"{label} (projected from toolchain.toml)",
        )
    )


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write text atomically using a temporary file and replace."""
    tmp_path = path.with_name(f".{path.name}.tmp")
    try:
        tmp_path.write_text(content, encoding=encoding, newline="\n")
        tmp_path.replace(path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def project_all(
    repo_root: Path, check_only: bool = False
) -> tuple[int, list[str], dict[str, str]]:
    """Project or verify toolchain definitions across all governed files.

    Returns:
        (exit_code, error_messages, projected_contents_map)
    """
    try:
        toolchain = load_toolchain(repo_root)
    except FileNotFoundError:
        return 1, [f"toolchain.toml not found at {repo_root}"], {}

    errors: list[str] = []
    projected_map: dict[str, str] = {}
    pending_writes: list[tuple[Path, str]] = []

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

        projected_map[rel_path] = projected

        if original != projected:
            diff = diff_text(rel_path, original, projected)
            if check_only:
                errors.append(
                    f"{rel_path} has drifted from toolchain.toml projection:\n{diff}"
                )
            else:
                pending_writes.append((file_path, projected))

    if errors:
        return 1, errors, projected_map

    if not check_only:
        for file_path, projected in pending_writes:
            try:
                atomic_write_text(file_path, projected, encoding="utf-8")
            except OSError as exc:
                errors.append(f"{file_path}: failed to write: {exc}")

    if errors:
        return 1, errors, projected_map

    return 0, [], projected_map


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for workflow projection."""
    parser = argparse.ArgumentParser(
        description="Project toolchain versions and container images into workflows and actions."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="Repository root directory (defaults to repo root of script)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether files match toolchain projection without modifying them.",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    status, errors, _ = project_all(repo_root, check_only=args.check)

    if status != 0:
        for error in errors:
            print(error, file=sys.stderr)
        if args.check:
            print(
                "ERROR: Workflow/action projection check failed. "
                "Run 'python tools/generate_workflows.py' to update.",
                file=sys.stderr,
            )
        return status

    if args.check:
        print("Workflow projection OK")
    else:
        print("Workflow projection updated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

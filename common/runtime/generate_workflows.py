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


def project_setup_minio_action(content: str, toolchain: dict) -> str:
    """Project MinIO container images into setup-minio composite action."""
    images = toolchain["images"]
    minio_img = images["minio"]
    minio_client_img = images["minio_client"]

    def replace_minio_server(match: re.Match[str]) -> str:
        indent = match.group(1)
        cur_img = match.group(2)
        end = match.group(3)
        if cur_img.strip("\x22\x27") == minio_img:
            return match.group(0)
        return f"{indent}{minio_img}{end}"

    content = re.sub(
        r"(?m)^(\s*)[\x22\x27]?([^\s\\\x22\x27]+)[\x22\x27]?(\s*\\\n\s*server /data)",
        replace_minio_server,
        content,
    )

    def replace_minio_client(match: re.Match[str]) -> str:
        prefix = match.group(1)
        cur_img = match.group(2)
        end = match.group(3)
        if cur_img.strip("\x22\x27") == minio_client_img:
            return match.group(0)
        return f"{prefix}{minio_client_img}{end}"

    content = re.sub(
        r"(?m)(docker run [^\n]*?--entrypoint /bin/sh\s+)[\x22\x27]?([^\s\\\x22\x27]+)[\x22\x27]?(\s*\\)",
        replace_minio_client,
        content,
    )
    return content


def project_setup_e2e_tests_action(content: str, toolchain: dict) -> str:
    """Project uv version into setup-e2e-tests composite action."""
    uv_version = toolchain["runtime"]["uv"]
    pattern = (
        r"(?m)(name:\s*[\x22\x27]?Install uv[\x22\x27]?\s*\n"
        r"(?:\s+.*\n)*?\s+version:\s*)[\x22\x27][^\x22\x27]+[\x22\x27]"
    )
    return re.sub(pattern, r"\g<1>" + f'"{uv_version}"', content)


def project_setup_backend_env_action(content: str, toolchain: dict) -> str:
    """Project default uv and python versions into setup-backend-env composite action."""
    runtime = toolchain["runtime"]
    uv_version = runtime["uv"]
    python_version = runtime["python"]
    content = re.sub(
        r"(?m)^(\s+uv-version:\s*\n(?:\s+.*\n)*?\s+default:\s*)[\x22\x27][^\x22\x27]+[\x22\x27]",
        r"\g<1>" + f"'{uv_version}'",
        content,
    )
    content = re.sub(
        r"(?m)^(\s+python-version:\s*\n(?:\s+.*\n)*?\s+default:\s*)[\x22\x27][^\x22\x27]+[\x22\x27]",
        r"\g<1>" + f"'{python_version}'",
        content,
    )
    return content


def project_compose(content: str, toolchain: dict) -> str:
    """Project service images and ARG defaults into docker-compose files."""
    images = toolchain["images"]

    def make_replacer(expected: str) -> Callable[[re.Match[str]], str]:
        def repl(m: re.Match[str]) -> str:
            prefix = m.group(1)
            cur = m.group(2)
            suffix = m.group(3)
            if cur.strip("\x22\x27") == expected:
                return m.group(0)
            return f"{prefix}{expected}{suffix}"

        return repl

    # postgres service
    content = re.sub(
        r"(?m)^(\s{2}postgres:\s*\n(?:\s{4}[^\n]*\n)*?\s{4}image:\s*)[\x22\x27]?([^\s#\x22\x27]+)[\x22\x27]?(.*)$",
        make_replacer(images["postgres"]),
        content,
    )
    # minio service
    content = re.sub(
        r"(?m)^(\s{2}minio:\s*\n(?:\s{4}[^\n]*\n)*?\s{4}image:\s*)[\x22\x27]?([^\s#\x22\x27]+)[\x22\x27]?(.*)$",
        make_replacer(images["minio"]),
        content,
    )
    # minio-init service
    content = re.sub(
        r"(?m)^(\s{2}minio-init:\s*\n(?:\s{4}[^\n]*\n)*?\s{4}image:\s*)[\x22\x27]?([^\s#\x22\x27]+)[\x22\x27]?(.*)$",
        make_replacer(images["minio_client"]),
        content,
    )

    if "frontend_node" in images:
        content = re.sub(
            r"\$\{NODE_IMAGE:-[^}]+}",
            f"${{NODE_IMAGE:-{images['frontend_node']}}}",
            content,
        )
    if "backend_uv" in images:
        content = re.sub(
            r"\$\{UV_IMAGE:-[^}]+}",
            f"${{UV_IMAGE:-{images['backend_uv']}}}",
            content,
        )
    if "backend_python" in images:
        content = re.sub(
            r"\$\{PYTHON_IMAGE:-[^}]+}",
            f"${{PYTHON_IMAGE:-{images['backend_python']}}}",
            content,
        )
    return content


def project_backend_dockerfile(content: str, toolchain: dict) -> str:
    """Project base images into backend Dockerfile."""
    images = toolchain["images"]
    content = re.sub(
        r"(?m)^ARG PYTHON_IMAGE=.*$",
        f"ARG PYTHON_IMAGE={images['backend_python']}",
        content,
    )
    content = re.sub(
        r"(?m)^ARG UV_IMAGE=.*$",
        f"ARG UV_IMAGE={images['backend_uv']}",
        content,
    )
    return content


def project_frontend_dockerfile(content: str, toolchain: dict) -> str:
    """Project base node image into frontend Dockerfile."""
    images = toolchain["images"]
    return re.sub(
        r"(?m)^ARG NODE_IMAGE=.*$",
        f"ARG NODE_IMAGE={images['frontend_node']}",
        content,
    )


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
    ".github/actions/setup-backend-env/action.yml": (
        project_setup_backend_env_action,
        False,
    ),
    "docker-compose.yml": (project_compose, False),
    "docker-compose.pr-preview.yml": (project_compose, False),
    "apps/backend/Dockerfile": (project_backend_dockerfile, False),
    "apps/frontend/Dockerfile": (project_frontend_dockerfile, False),
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
                try:
                    file_path.write_text(projected, encoding="utf-8")
                except OSError as exc:
                    errors.append(f"{rel_path}: failed to write: {exc}")

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

"""Namespace and resource naming helpers for isolated test runs."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

CACHE_DIR = Path.home() / ".cache" / "finance_report"
ACTIVE_NAMESPACES_FILE = CACHE_DIR / "active_namespaces.json"
MAX_POSTGRES_IDENTIFIER_LENGTH = 63
TEST_DB_PREFIX = "finance_report_test_"
MAX_NAMESPACE_LENGTH = MAX_POSTGRES_IDENTIFIER_LENGTH - len(TEST_DB_PREFIX)
MAX_S3_BUCKET_LENGTH = 63


def sanitize_namespace(name: str) -> str:
    """Convert a branch or workspace name to a safe identifier."""
    if not name or not name.strip():
        raise ValueError(f"Invalid namespace '{name}'")
    safe = name.lower().replace("/", "_").replace("-", "_")
    safe = "".join(c if c.isalnum() or c == "_" else "" for c in safe)
    while "__" in safe:
        safe = safe.replace("__", "_")
    safe = safe.strip("_")
    if not safe:
        raise ValueError(f"Invalid namespace '{name}'")
    return safe


def shorten_identifier(value: str, max_length: int, separator: str = "_") -> str:
    """Shorten a stable identifier and preserve uniqueness with a hash suffix."""
    if len(value) <= max_length:
        return value

    digest = hashlib.sha256(value.encode()).hexdigest()[:8]
    prefix_length = max_length - len(separator) - len(digest)
    if prefix_length < 1:
        raise ValueError(f"Identifier max_length too short: {max_length}")

    prefix = value[:prefix_length].rstrip("_-")
    return f"{prefix}{separator}{digest}"


def get_namespace(
    *,
    branch_name: str | None = None,
    workspace_id: str | None = None,
    run: Callable[..., Any] = subprocess.run,
    cwd_getter: Callable[[], Path] = Path.cwd,
) -> str:
    """Generate a unique test namespace based on env, branch, and path."""
    branch = branch_name if branch_name is not None else os.environ.get("BRANCH_NAME")
    workspace = (
        workspace_id if workspace_id is not None else os.environ.get("WORKSPACE_ID")
    )

    if branch:
        namespace = sanitize_namespace(branch)
        if workspace:
            try:
                namespace = f"{namespace}_{sanitize_namespace(workspace)}"
            except ValueError:
                pass
        return shorten_identifier(namespace, MAX_NAMESPACE_LENGTH, separator="_")

    try:
        result = run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        git_branch = result.stdout.strip()
        if git_branch:
            namespace = sanitize_namespace(git_branch)
            path_hash = hashlib.sha256(
                str(cwd_getter().absolute()).encode()
            ).hexdigest()[:8]
            return shorten_identifier(
                f"{namespace}_{path_hash}", MAX_NAMESPACE_LENGTH, separator="_"
            )
    except Exception:
        pass

    path_hash = hashlib.sha256(str(cwd_getter().absolute()).encode()).hexdigest()[:8]
    return f"default_{path_hash}"


def get_test_db_name(namespace: str) -> str:
    """Generate a bounded PostgreSQL test database name from a namespace."""
    safe_namespace = shorten_identifier(namespace, MAX_NAMESPACE_LENGTH, separator="_")
    return f"{TEST_DB_PREFIX}{safe_namespace}"


def get_s3_bucket(namespace: str, base_bucket: str = "statements") -> str:
    """Generate a bounded S3 bucket name from a namespace."""
    safe_namespace = namespace.replace("_", "-")
    bucket = f"{base_bucket}-{safe_namespace}"
    if len(bucket) <= MAX_S3_BUCKET_LENGTH:
        return bucket

    digest = hashlib.sha256(bucket.encode()).hexdigest()[:8]
    prefix_length = MAX_S3_BUCKET_LENGTH - len(base_bucket) - 2 - len(digest)
    if prefix_length < 1:
        raise ValueError(f"Base bucket name too long: {base_bucket}")

    prefix = safe_namespace[:prefix_length].rstrip("-")
    return f"{base_bucket}-{prefix}-{digest}"


def get_env_suffix(namespace: str) -> str:
    """Return the compose/container suffix for a test namespace."""
    return f"-{namespace}"


def load_active_namespaces(
    active_namespaces_file: Path = ACTIVE_NAMESPACES_FILE,
    cache_dir: Path = CACHE_DIR,
) -> list[str]:
    """Load tracked active namespaces from persistent storage."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    if not active_namespaces_file.exists():
        return []
    try:
        return json.loads(active_namespaces_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_active_namespaces(
    namespaces: list[str],
    active_namespaces_file: Path = ACTIVE_NAMESPACES_FILE,
    cache_dir: Path = CACHE_DIR,
) -> None:
    """Save tracked active namespaces to persistent storage."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    active_namespaces_file.write_text(
        json.dumps(namespaces, indent=2), encoding="utf-8"
    )


def register_namespace(
    namespace: str,
    active_namespaces_file: Path = ACTIVE_NAMESPACES_FILE,
    cache_dir: Path = CACHE_DIR,
) -> None:
    """Register a namespace as active."""
    namespaces = load_active_namespaces(active_namespaces_file, cache_dir)
    if namespace not in namespaces:
        namespaces.append(namespace)
        save_active_namespaces(namespaces, active_namespaces_file, cache_dir)


def unregister_namespace(
    namespace: str,
    active_namespaces_file: Path = ACTIVE_NAMESPACES_FILE,
    cache_dir: Path = CACHE_DIR,
) -> None:
    """Unregister a namespace after cleanup."""
    namespaces = load_active_namespaces(active_namespaces_file, cache_dir)
    if namespace in namespaces:
        namespaces.remove(namespace)
        save_active_namespaces(namespaces, active_namespaces_file, cache_dir)

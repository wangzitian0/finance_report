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


def is_droppable_test_db(name: str | None) -> bool:
    """Return True only for a test database: the name starts with the test prefix.

    A session teardown drops its database. With DATABASE_URL exported and no
    TEST_NAMESPACE, the session database is the DATABASE_URL database, which
    can be a development database. This check keeps the drop off that database.
    """
    return bool(name) and name.startswith(TEST_DB_PREFIX.rstrip("_"))


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
    workspace = workspace_id if workspace_id is not None else os.environ.get("WORKSPACE_ID")

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
            path_hash = hashlib.sha256(str(cwd_getter().absolute()).encode()).hexdigest()[:8]
            return shorten_identifier(f"{namespace}_{path_hash}", MAX_NAMESPACE_LENGTH, separator="_")
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


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _load_namespace_leases(
    active_namespaces_file: Path = ACTIVE_NAMESPACES_FILE,
) -> dict[str, list[int]]:
    if not active_namespaces_file.exists():
        return {}
    try:
        raw = json.loads(active_namespaces_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(raw, list):
        return {str(ns): [] for ns in raw if isinstance(ns, str) and ns}
    if not isinstance(raw, dict):
        return {}
    leases: dict[str, list[int]] = {}
    for ns, pids in raw.items():
        if not isinstance(ns, str) or not ns or not isinstance(pids, list):
            continue
        live = [int(p) for p in pids if isinstance(p, int) and _is_pid_alive(int(p))]
        if live:
            leases[ns] = sorted(set(live))
    return leases


def _save_namespace_leases(
    leases: dict[str, list[int]],
    active_namespaces_file: Path = ACTIVE_NAMESPACES_FILE,
    cache_dir: Path = CACHE_DIR,
) -> None:
    import tempfile

    cache_dir.mkdir(parents=True, exist_ok=True)
    active_namespaces_file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".active_namespaces_", suffix=".tmp", dir=str(active_namespaces_file.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(leases, fh, indent=2)
        os.replace(tmp_name, active_namespaces_file)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_active_namespaces(
    active_namespaces_file: Path = ACTIVE_NAMESPACES_FILE,
    cache_dir: Path = CACHE_DIR,
) -> list[str]:
    """Load tracked active namespaces with live PIDs from persistent storage."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    return sorted(_load_namespace_leases(active_namespaces_file))


def save_active_namespaces(
    namespaces: list[str] | dict[str, list[int]],
    active_namespaces_file: Path = ACTIVE_NAMESPACES_FILE,
    cache_dir: Path = CACHE_DIR,
) -> None:
    """Save tracked active namespaces to persistent storage."""
    leases = {ns: [] for ns in namespaces} if isinstance(namespaces, list) else namespaces
    _save_namespace_leases(leases, active_namespaces_file, cache_dir)


def register_namespace(
    namespace: str,
    active_namespaces_file: Path = ACTIVE_NAMESPACES_FILE,
    cache_dir: Path = CACHE_DIR,
    *,
    pid: int | None = None,
) -> None:
    """Register a namespace lease for the current process."""
    holder = os.getpid() if pid is None else pid
    leases = _load_namespace_leases(active_namespaces_file)
    holders = set(leases.get(namespace, []))
    if holder not in holders:
        holders.add(holder)
        leases[namespace] = sorted(holders)
        _save_namespace_leases(leases, active_namespaces_file, cache_dir)


def unregister_namespace(
    namespace: str,
    active_namespaces_file: Path = ACTIVE_NAMESPACES_FILE,
    cache_dir: Path = CACHE_DIR,
    *,
    pid: int | None = None,
) -> None:
    """Unregister the current process lease for ``namespace``."""
    holder = os.getpid() if pid is None else pid
    leases = _load_namespace_leases(active_namespaces_file)
    if namespace not in leases:
        return
    remaining = [p for p in leases[namespace] if p != holder]
    if remaining:
        leases[namespace] = remaining
    else:
        leases.pop(namespace, None)
    _save_namespace_leases(leases, active_namespaces_file, cache_dir)

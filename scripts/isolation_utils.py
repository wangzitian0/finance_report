#!/usr/bin/env python3
"""
Isolation utilities for multi-repo/multi-branch parallel development.

Provides namespace generation based on BRANCH_NAME + WORKSPACE_ID
to isolate test databases, containers, and S3 buckets.
"""

import hashlib
import os
import subprocess
from pathlib import Path


def get_namespace() -> str:
    """
    Generate a unique namespace for test isolation.

    Priority:
    1. BRANCH_NAME (explicit) + WORKSPACE_ID (optional)
    2. Git branch (auto-detect) + repo path hash
    3. "default" + repo path hash (with warning)

    Returns:
        Namespace string (safe for DB/container names)
    """
    branch = os.environ.get("BRANCH_NAME")
    workspace = os.environ.get("WORKSPACE_ID")

    if branch:
        namespace = sanitize_namespace(branch)
        if workspace:
            namespace = f"{namespace}_{workspace}"
        return namespace

    # Git auto-detection - ALWAYS add path hash for multi-repo safety
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        git_branch = result.stdout.strip()

        if git_branch:
            namespace = sanitize_namespace(git_branch)

            # Add repo path hash for uniqueness across repo copies
            repo_path = Path.cwd().absolute()
            path_hash = hashlib.sha256(str(repo_path).encode()).hexdigest()[:8]

            return f"{namespace}_{path_hash}"
    except Exception:
        pass

    # Fallback: Use path hash even for "default" to prevent conflicts
    repo_path = Path.cwd().absolute()
    path_hash = hashlib.sha256(str(repo_path).encode()).hexdigest()[:8]

    print("⚠️  WARNING: No BRANCH_NAME set and git detection failed")
    print(f"   Using 'default_{path_hash}' namespace")
    print("   Set BRANCH_NAME=<branch> for better isolation")

    return f"default_{path_hash}"


def sanitize_namespace(name: str) -> str:
    """
    Convert branch/tag name to safe identifier.

    Examples:
        "feature/auth-v2" -> "feature_auth_v2"
        "fix-bug-#123" -> "fix_bug_123"

    Raises:
        ValueError: If name results in empty identifier after sanitization
    """
    if not name or not name.strip():
        raise ValueError(f"Invalid namespace '{name}': input is empty or whitespace")

    safe = name.replace("/", "_").replace("-", "_").replace("#", "").lower()

    if not safe or not safe.strip("_"):
        raise ValueError(
            f"Invalid namespace '{name}': results in empty identifier after sanitization"
        )

    return safe


def get_test_db_name(namespace: str) -> str:
    """Generate test database name from namespace."""
    return f"finance_report_test_{namespace}"


def get_env_suffix(namespace: str) -> str:
    """Generate ENV_SUFFIX for docker-compose from namespace."""
    return f"-{namespace}"


def get_s3_bucket(namespace: str, base_bucket: str = "statements") -> str:
    """Generate S3 bucket name from namespace (uses hyphens, not underscores)."""
    safe_namespace = namespace.replace("_", "-")
    return f"{base_bucket}-{safe_namespace}"


if __name__ == "__main__":
    ns = get_namespace()
    print(f"Namespace: {ns}")
    print(f"Test DB: {get_test_db_name(ns)}")
    print(f"ENV_SUFFIX: {get_env_suffix(ns)}")
    print(f"S3 Bucket: {get_s3_bucket(ns)}")

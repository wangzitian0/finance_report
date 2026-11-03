"""AC-testing.package-lifecycle.3: pin a live proof to the deployment it names.

A release tag and a short commit SHA can name the same deployment. The backend
reports the tag and the frontend reports the short SHA. A live proof therefore
compares versions by commit identity, never by plain string equality.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_expected_commit(
    expected_version: str, repo_root: Path = REPO_ROOT
) -> str | None:
    """Return the commit that ``expected_version`` names, or None when git cannot resolve it.

    The post-merge gate checks out a shallow commit, so a release tag need not exist
    locally. When ``git rev-parse`` cannot resolve the tag directly, fall back to
    ``COMMIT_REF`` or ``GITHUB_SHA`` if present and valid in the checkout.
    """
    candidates = [expected_version]
    for env_key in ("COMMIT_REF", "GITHUB_SHA"):
        env_val = os.getenv(env_key, "").strip()
        if env_val and env_val not in candidates:
            candidates.append(env_val)
    for ref in candidates:
        result = subprocess.run(
            [
                "git",
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{ref}^{{commit}}",
            ],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    return None


def assert_pinned_deployment(
    payload: dict, expected_version: str, expected_commit: str | None
) -> None:
    """Release tags must match exactly; an observed SHA must name their commit."""
    observed = [payload.get("git_sha"), payload.get("version")]
    if not all(observed):
        raise AssertionError("deployed service must publish version and git_sha")
    for version in observed:
        names_same_commit = bool(
            expected_commit
            and re.fullmatch(r"[0-9a-f]{7,40}", version)
            and expected_commit.startswith(version)
        )
        if version != expected_version and not names_same_commit:
            raise AssertionError(
                f"deployed version {version} does not match pinned target {expected_version}"
            )

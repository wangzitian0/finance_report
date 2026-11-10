"""AC-testing.package-lifecycle.3: pin a live proof to the deployment it names."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_expected_commit(
    expected_version: str, repo_root: Path = REPO_ROOT
) -> str | None:
    """Resolve expected_version via git, CI refs, or clean-room hook HEAD."""
    candidates = [expected_version]
    for env_key in ("COMMIT_REF", "GITHUB_SHA"):
        if (val := os.getenv(env_key, "").strip()) and val not in candidates:
            candidates.append(val)
    if os.getenv("HOOK_SLOT", "").strip():
        hook_refs = {
            val
            for k in ("EXPECTED_SHA", "APP_VERSION_REF")
            if (val := os.getenv(k, "").strip())
        }
        if expected_version in hook_refs and "HEAD" not in candidates:
            candidates.append("HEAD")
    for ref in candidates:
        cmd = ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"]
        res = subprocess.run(cmd, cwd=repo_root, text=True, capture_output=True)
        if res.returncode == 0:
            return res.stdout.strip()
    return None


def assert_pinned_deployment(
    payload: dict, expected_version: str, expected_commit: str | None
) -> None:
    """Release tags must match exactly; an observed SHA must name their commit."""
    observed = [payload.get("git_sha"), payload.get("version")]
    if not all(observed):
        raise AssertionError("deployed service must publish version and git_sha")
    for version in observed:
        same = bool(
            expected_commit
            and re.fullmatch(r"[0-9a-f]{7,40}", version)
            and expected_commit.startswith(version)
        )
        if version != expected_version and not same:
            raise AssertionError(
                f"deployed version {version} does not match pinned target {expected_version}"
            )

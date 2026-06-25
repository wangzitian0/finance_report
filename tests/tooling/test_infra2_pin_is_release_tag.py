"""PR-time gate: the pinned infra2 submodule must be an infra2 RELEASE TAG.

deploy_v2 staging/prod reject a raw sha as `iac_ref` — it must be a `vX.Y.Z`
release tag (the immutable, reviewed coordinate that passed infra2's release
ritual). A git submodule pins by sha, so it is possible to bump the app's infra2
submodule to an *unreleased* infra2 commit; that produces an un-releasable app
state that, without this gate, only blows up at deploy time
(`deploy_v2 ... requires a release-tag iac_ref, got a 'sha' ref`).

This gate fails the PR instead, so "pinned at an unreleased infra2 commit" is
caught at merge. It asserts behaviour (the real pin resolves to a tag), not the
text of any workflow.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from common.ci.release_coordinate import resolve_infra2_release_tag

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT / "repo"


def test_infra2_submodule_is_pinned_at_a_release_tag() -> None:
    """The app's infra2 submodule must point at a vX.Y.Z release tag (deploy_v2 iac_ref)."""
    if not REPO.exists():
        pytest.skip("infra2 submodule not checked out")
    # Resolves the pinned sha back to its exact release tag, or raises RuntimeError
    # with a clear message if the pin is not a release tag.
    iac_ref = resolve_infra2_release_tag(str(REPO))
    assert iac_ref.startswith("v"), iac_ref


def test_untagged_pin_fails_closed(tmp_path: Path) -> None:
    """A submodule pinned at a non-tag commit fails closed (the gate has teeth)."""
    fake = tmp_path / "repo"
    fake.mkdir()
    subprocess.run(["git", "-C", str(fake), "init", "-q"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(fake),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "no tag here",
        ],
        check=True,
    )
    with pytest.raises(RuntimeError, match="NOT a release tag|not a vX.Y.Z"):
        resolve_infra2_release_tag(str(fake))

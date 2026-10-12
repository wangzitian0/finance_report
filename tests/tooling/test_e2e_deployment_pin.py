"""AC-testing.package-lifecycle.3: a live proof pins a deployment by commit identity (#2332).

The backend reports the release tag and the frontend reports the short SHA of the
same commit. Plain string equality fails for one of them.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.e2e.deployment_pin import assert_pinned_deployment, resolve_expected_commit

COMMIT = "ff473b9d2c1e4a5b6c7d8e9f0a1b2c3d4e5f6a7b"
TAG = "v0.1.74"


def _payload(git_sha: str | None, version: str | None = None) -> dict:
    return {"git_sha": git_sha, "version": git_sha if version is None else version}


def test_the_release_tag_matches_itself_without_a_resolved_commit() -> None:
    assert_pinned_deployment(_payload(TAG), TAG, None)


def test_a_short_sha_of_the_tagged_commit_matches_the_tag() -> None:
    assert_pinned_deployment(_payload("ff473b9"), TAG, COMMIT)


def test_a_full_sha_of_the_tagged_commit_matches_the_tag() -> None:
    assert_pinned_deployment(_payload(COMMIT), TAG, COMMIT)


def test_the_backend_tag_and_the_frontend_sha_both_pass_for_one_deployment() -> None:
    assert_pinned_deployment({"git_sha": TAG, "version": TAG}, TAG, COMMIT)
    assert_pinned_deployment({"git_sha": "ff473b9", "version": "ff473b9"}, TAG, COMMIT)


@pytest.mark.parametrize(
    "observed",
    ["abcdef0", "ff473b8", "0ff473b"],
    ids=["other-commit", "one-digit-off", "suffix-not-prefix"],
)
def test_a_sha_of_another_commit_fails(observed: str) -> None:
    with pytest.raises(AssertionError, match="does not match pinned target"):
        assert_pinned_deployment(_payload(observed), TAG, COMMIT)


def test_a_sha_cannot_be_compared_when_the_tag_did_not_resolve() -> None:
    with pytest.raises(AssertionError, match="does not match pinned target"):
        assert_pinned_deployment(_payload("ff473b9"), TAG, None)


@pytest.mark.parametrize("observed", ["ff473b", "FF473B9", "ff473b9g", "v0.1.73"])
def test_a_malformed_or_other_version_fails(observed: str) -> None:
    with pytest.raises(AssertionError, match="does not match pinned target"):
        assert_pinned_deployment(_payload(observed), TAG, COMMIT)


@pytest.mark.parametrize(
    "payload",
    [{}, {"git_sha": TAG}, {"version": TAG}, {"git_sha": "", "version": TAG}],
    ids=["empty", "no-version", "no-git-sha", "empty-git-sha"],
)
def test_a_service_that_hides_its_version_fails(payload: dict) -> None:
    with pytest.raises(AssertionError, match="must publish version and git_sha"):
        assert_pinned_deployment(payload, TAG, COMMIT)


def test_one_wrong_field_fails_even_when_the_other_matches() -> None:
    with pytest.raises(AssertionError, match="does not match pinned target"):
        assert_pinned_deployment({"git_sha": TAG, "version": "v0.1.73"}, TAG, COMMIT)


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@test.example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@test.example.com",
    }
    return subprocess.run(
        ["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_an_annotated_tag_resolves_to_its_commit(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "--allow-empty", "-q", "-m", "release")
    commit = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "tag", "-a", "v9.9.9", "-m", "Release v9.9.9")

    assert resolve_expected_commit("v9.9.9", tmp_path) == commit
    assert resolve_expected_commit(commit[:7], tmp_path) == commit


def test_an_unknown_tag_resolves_to_nothing(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "--allow-empty", "-q", "-m", "release")

    assert resolve_expected_commit("v0.0.0-missing", tmp_path) is None

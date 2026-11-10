"""AC-testing.package-lifecycle.3: pin live proofs by commit identity (#2332, #2943)."""

from __future__ import annotations
import os, subprocess  # noqa: E401
from pathlib import Path
import pytest
from tests.e2e.deployment_pin import assert_pinned_deployment, resolve_expected_commit

COMMIT, TAG = "ff473b9d2c1e4a5b6c7d8e9f0a1b2c3d4e5f6a7b", "v0.1.74"
ENV_KEYS = ("COMMIT_REF", "GITHUB_SHA", "HOOK_SLOT", "EXPECTED_SHA", "APP_VERSION_REF")
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t.co",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t.co",
}


def _payload(sha: str | None, ver: str | None = None) -> dict:
    return {"git_sha": sha, "version": sha if ver is None else ver}


def _git(repo: Path, *args: str) -> str:
    cmd = ["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", *args]
    res = subprocess.run(cmd, cwd=repo, env={**os.environ, **GIT_ENV}, check=True, capture_output=True)  # fmt: skip
    return res.stdout.decode().strip()


def _init_repo(repo: Path, monkeypatch: pytest.MonkeyPatch | None = None) -> str:
    for env_key in ENV_KEYS if monkeypatch else ():
        monkeypatch.delenv(env_key, raising=False)
    _git(repo, "init", "-q")
    _git(repo, "commit", "--allow-empty", "-q", "-m", "release")
    return _git(repo, "rev-parse", "HEAD")


def test_the_release_tag_matches_itself_without_a_resolved_commit() -> None:
    assert_pinned_deployment(_payload(TAG), TAG, None)
    assert_pinned_deployment(_payload("ff473b9"), TAG, COMMIT)
    assert_pinned_deployment(_payload(COMMIT), TAG, COMMIT)
    assert_pinned_deployment({"git_sha": "ff473b9", "version": "ff473b9"}, TAG, COMMIT)
    with pytest.raises(AssertionError, match="does not match pinned target"):
        assert_pinned_deployment(_payload("ff473b9"), TAG, None)
    with pytest.raises(AssertionError, match="does not match pinned target"):
        assert_pinned_deployment({"git_sha": TAG, "version": "v0.1.73"}, TAG, COMMIT)


@pytest.mark.parametrize("observed", ["abcdef0", "ff473b8", "0ff473b"], ids=["other-commit", "one-digit-off", "suffix-not-prefix"])  # fmt: skip
def test_a_sha_of_another_commit_fails(observed: str) -> None:
    with pytest.raises(AssertionError, match="does not match pinned target"):
        assert_pinned_deployment(_payload(observed), TAG, COMMIT)


@pytest.mark.parametrize("observed", ["ff473b", "FF473B9", "ff473b9g", "v0.1.73"])
def test_a_malformed_or_other_version_fails(observed: str) -> None:
    with pytest.raises(AssertionError, match="does not match pinned target"):
        assert_pinned_deployment(_payload(observed), TAG, COMMIT)


@pytest.mark.parametrize("payload", [{}, {"git_sha": TAG}, {"version": TAG}, {"git_sha": "", "version": TAG}], ids=["empty", "no-version", "no-git-sha", "empty-git-sha"])  # fmt: skip
def test_a_service_that_hides_its_version_fails(payload: dict) -> None:
    with pytest.raises(AssertionError, match="must publish version and git_sha"):
        assert_pinned_deployment(payload, TAG, COMMIT)


def test_an_annotated_tag_resolves_to_its_commit(tmp_path: Path) -> None:
    commit = _init_repo(tmp_path)
    _git(tmp_path, "tag", "-a", "v9.9.9", "-m", "Release v9.9.9")
    assert resolve_expected_commit("v9.9.9", tmp_path) == commit
    assert resolve_expected_commit(commit[:7], tmp_path) == commit


def test_an_unknown_tag_resolves_to_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    _init_repo(tmp_path, monkeypatch)
    assert resolve_expected_commit("v0.0.0-missing", tmp_path) is None


def test_unknown_tag_falls_back_to_commit_ref_or_github_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    commit = _init_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("COMMIT_REF", commit)
    assert resolve_expected_commit("v0.0.0-missing", tmp_path) == commit
    monkeypatch.delenv("COMMIT_REF")
    monkeypatch.setenv("GITHUB_SHA", commit)
    assert resolve_expected_commit("v0.0.0-missing", tmp_path) == commit


def test_clean_room_hook_checkout_resolves_head_for_matching_version_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    commit = _init_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("HOOK_SLOT", "staging_gate")
    monkeypatch.setenv("EXPECTED_SHA", "v0.2.58")
    assert resolve_expected_commit("v0.2.58", tmp_path) == commit
    assert_pinned_deployment(_payload(commit[:7]), "v0.2.58", commit)
    monkeypatch.delenv("EXPECTED_SHA")
    monkeypatch.setenv("APP_VERSION_REF", "v0.2.58")
    assert resolve_expected_commit("v0.2.58", tmp_path) == commit


def test_clean_room_hook_checkout_rejects_unmatched_tag_or_non_hook_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    _init_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("HOOK_SLOT", "staging_gate")
    monkeypatch.setenv("EXPECTED_SHA", "v0.2.58")
    assert resolve_expected_commit("v0.2.57", tmp_path) is None
    monkeypatch.setenv("HOOK_SLOT", "")
    assert resolve_expected_commit("v0.2.58", tmp_path) is None

"""tests/e2e/test_version_check.py accepts the deployed release tag (wangzitian0/infra2#1823).

Staging serves ``git_sha == version == <release tag>``. The hook runner sets
``APP_VERSION_REF`` to the same tag. Resolving the tag to its commit and comparing the
commit with the served tag failed staging train v3.1.128 (run 44894442756).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tests.e2e import test_version_check as module

COMMIT = "962a038f0629ad1db0860f2e9a2cb6a063cd97c1"


class _Client:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get(self, _url: str) -> SimpleNamespace:
        return SimpleNamespace(status_code=200, json=lambda: self._payload)


def _run(monkeypatch: pytest.MonkeyPatch, payload: dict, expected: str) -> None:
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_kw: _Client(payload))
    monkeypatch.setattr(module, "resolve_expected_commit", lambda _ref: COMMIT)
    config = SimpleNamespace(APP_URL="https://report-staging.example", EXPECTED_SHA=expected, TEST_ENV="staging")
    asyncio.run(module.test_deployed_version_matches_source(config))


def test_a_served_release_tag_matches_the_expected_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    _run(monkeypatch, {"git_sha": "v0.2.92", "version": "v0.2.92"}, "v0.2.92")


def test_a_served_short_sha_of_the_tag_commit_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    _run(monkeypatch, {"git_sha": COMMIT[:7], "version": COMMIT[:7]}, "v0.2.92")


@pytest.mark.parametrize("served", ["v0.2.91", "0000000"])
def test_another_release_fails(monkeypatch: pytest.MonkeyPatch, served: str) -> None:
    with pytest.raises(AssertionError, match="does not match pinned target v0.2.92"):
        _run(monkeypatch, {"git_sha": served, "version": served}, "v0.2.92")

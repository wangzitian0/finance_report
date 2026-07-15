"""Behavioral locks for the CODE-ONLY runtime slice of #1867."""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import pytest

from common.runtime import (
    github_api,
    release_coordinate,
    release_evidence,
    release_images,
)
from common.runtime import wait_post_merge_train_turn as train_wait
from common.testing import wait_for_cheap_ci


def test_AC_runtime_github_api_1_runtime_and_testing_share_github_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC-runtime.github-api.1: clients, UTC parsing, and output writing remain shared."""

    assert train_wait.GitHubActionsClient is github_api.GitHubActionsClient
    assert wait_for_cheap_ci.GitHubActionsClient is github_api.GitHubActionsClient
    assert train_wait.parse_github_time is github_api.parse_github_time
    assert release_evidence._write_github_output is github_api.write_github_output
    assert release_images._write_github_output is github_api.write_github_output
    assert release_coordinate.write_github_output is github_api.write_github_output

    assert github_api.parse_github_time("2026-07-15T12:00:00Z") == datetime(
        2026, 7, 15, 12, tzinfo=UTC
    )
    assert github_api.parse_github_time(None) is None

    output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    github_api.write_github_output({"run_id": "123", "status": "success"})
    assert output.read_text(encoding="utf-8") == "run_id=123\nstatus=success\n"

    requests: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
        assert timeout == 20
        url = request.full_url  # type: ignore[attr-defined]
        requests.append(url)
        if "/jobs" in url:
            return FakeResponse({"jobs": [{"id": 2}]})
        if "/actions/runs/42" in url:
            return FakeResponse({"id": 42})
        if "workflows/5/runs" in url and "&page=1" in url:
            return FakeResponse(
                {"workflow_runs": [{"id": number} for number in range(100)]}
            )
        if "workflows/5/runs" in url:
            return FakeResponse({"workflow_runs": []})
        return FakeResponse({"workflow_runs": [{"id": 1}]})

    monkeypatch.setattr(github_api.urllib.request, "urlopen", fake_urlopen)
    client = github_api.GitHubActionsClient(repository="owner/repo", token="secret")
    assert client.get_workflow_runs("abc") == [{"id": 1}]
    assert client.get_run_jobs(42) == [{"id": 2}]
    assert client.get_run_payload(42) == {"id": 42}
    assert len(client.list_workflow_runs(5)) == 100
    assert any("head_sha=abc" in url for url in requests)

    def raise_http_error(_request: object, *, timeout: int) -> FakeResponse:
        raise urllib.error.HTTPError(
            "https://api.github.com/example",
            401,
            "unauthorized",
            {},
            io.BytesIO(b"denied"),
        )

    monkeypatch.setattr(github_api.urllib.request, "urlopen", raise_http_error)
    with pytest.raises(RuntimeError, match="GitHub API HTTP 401"):
        client.get_workflow_runs("abc")

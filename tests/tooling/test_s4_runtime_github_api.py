"""Unit tests for shared GitHub API and Actions helpers."""

from __future__ import annotations

import ast
import io
import json
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import pytest
from infra2_sdk import ci as sdk_ci

from common.runtime import github_api, release_images
from common.testing import github_workflow_timing_summary

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_and_testing_share_github_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Shared GitHub API helpers are reused rather than duplicated."""
    assert release_images._write_github_output is github_api.write_github_output
    assert github_workflow_timing_summary.parse_github_time is github_api.parse_github_time
    assert github_api.parse_github_time is sdk_ci.parse_github_time
    assert github_api.write_github_output is sdk_ci.write_github_output

    helper_names = {"parse_github_time", "write_github_output", "_write_github_output"}
    found: dict[str, list[str]] = {name: [] for name in helper_names}
    for root_name in ("common", "tools"):
        for path in sorted((REPO_ROOT / root_name).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in found:
                    found[node.name].append(path.relative_to(REPO_ROOT).as_posix())
    assert found == {name: [] for name in helper_names}

    assert github_api.parse_github_time("2026-07-15T12:00:00Z") == datetime(2026, 7, 15, 12, tzinfo=UTC)
    assert github_api.parse_github_time(None) is None

    output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    github_api.write_github_output({"run_id": "123", "status": "success", "multiline": "a\nb"})
    text = output.read_text(encoding="utf-8")
    assert "run_id=123\nstatus=success\nmultiline<<" in text

    with pytest.raises(ValueError, match="invalid GitHub output key"):
        github_api.write_github_output({"not-a-key": "value"})

    requests: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
        assert timeout == 20
        url = request.full_url  # type: ignore[attr-defined]
        requests.append(url)
        return FakeResponse({"jobs": [{"id": 2}]} if "/jobs" in url else {"workflow_runs": [{"id": 1}]})

    monkeypatch.setattr(github_api.urllib.request, "urlopen", fake_urlopen)
    client = github_api.GitHubActionsClient(repository="owner/repo", token="secret")
    assert client.get_workflow_runs("abc") == [{"id": 1}]
    assert client.get_run_jobs(42) == [{"id": 2}]
    assert any("head_sha=abc" in url for url in requests)

    def raise_http_error(_req: object, *, timeout: int) -> FakeResponse:
        raise urllib.error.HTTPError("https://api.github.com/x", 401, "unauthorized", {}, io.BytesIO(b"denied"))

    monkeypatch.setattr(github_api.urllib.request, "urlopen", raise_http_error)
    with pytest.raises(RuntimeError, match="GitHub API HTTP 401.*denied"):
        client.get_workflow_runs("abc")

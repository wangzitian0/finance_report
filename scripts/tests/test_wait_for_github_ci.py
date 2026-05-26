import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import wait_for_github_ci as wait_ci  # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += seconds


def completed_process(
    payload: list[dict[str, object]],
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
    )


def test_AC8_13_21_wait_returns_when_matching_ci_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.21: Waiting stops when the matching CI run succeeds."""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed_process(
            [
                {
                    "databaseId": 123,
                    "status": "completed",
                    "conclusion": "success",
                    "url": "https://example.test/run/123",
                }
            ]
        )

    monkeypatch.setattr(wait_ci.subprocess, "run", fake_run)
    clock = FakeClock()

    result = wait_ci.wait_for_matching_ci(
        repo="owner/repo",
        sha="abc123",
        workflow="CI",
        branch="main",
        event="push",
        timeout_seconds=60,
        poll_seconds=5,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result.conclusion == "success"
    assert calls == [
        [
            "gh",
            "run",
            "list",
            "--repo",
            "owner/repo",
            "--workflow",
            "CI",
            "--branch",
            "main",
            "--commit",
            "abc123",
            "--event",
            "push",
            "--json",
            "databaseId,status,conclusion,url",
            "--limit",
            "10",
        ]
    ]
    assert clock.sleeps == []


def test_AC8_13_21_wait_fails_closed_on_failed_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.21: A failed matching CI run blocks deploy/provider validation."""

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return completed_process(
            [
                {
                    "databaseId": 124,
                    "status": "completed",
                    "conclusion": "failure",
                    "url": "https://example.test/run/124",
                }
            ]
        )

    monkeypatch.setattr(wait_ci.subprocess, "run", fake_run)
    clock = FakeClock()

    with pytest.raises(RuntimeError, match="matching CI run failed"):
        wait_ci.wait_for_matching_ci(
            repo="owner/repo",
            sha="def456",
            timeout_seconds=60,
            poll_seconds=5,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )


def test_AC8_13_43_failed_ci_error_includes_failed_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.43: Staging gate errors identify failed CI jobs before deploy."""

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if args[:3] == ["gh", "run", "list"]:
            return completed_process(
                [
                    {
                        "databaseId": 124,
                        "status": "completed",
                        "conclusion": "failure",
                        "url": "https://example.test/run/124",
                    }
                ]
            )
        if args[:3] == ["gh", "run", "view"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(
                    {
                        "jobs": [
                            {
                                "name": "Build Staging Images",
                                "status": "completed",
                                "conclusion": "failure",
                                "url": "https://example.test/run/124/job/1",
                            },
                            {
                                "name": "Calculate Unified Coverage",
                                "status": "completed",
                                "conclusion": "success",
                                "url": "https://example.test/run/124/job/2",
                            },
                            {
                                "name": "Downstream job",
                                "status": "completed",
                                "conclusion": "skipped",
                                "url": "https://example.test/run/124/job/4",
                            },
                            {
                                "name": "finish",
                                "status": "completed",
                                "conclusion": "failure",
                                "url": "https://example.test/run/124/job/3",
                            },
                        ]
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected gh command: {args}")

    monkeypatch.setattr(wait_ci.subprocess, "run", fake_run)
    clock = FakeClock()

    with pytest.raises(RuntimeError) as excinfo:
        wait_ci.wait_for_matching_ci(
            repo="owner/repo",
            sha="def456",
            timeout_seconds=60,
            poll_seconds=5,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    message = str(excinfo.value)
    assert "matching CI run failed before staging validation" in message
    assert "failed_jobs=Build Staging Images(failure), finish(failure)" in message
    assert "Downstream job" not in message
    assert "https://example.test/run/124" in message


def test_AC8_13_22_wait_polls_until_run_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.22: Staging deploy can wait for GitHub to create the CI run."""
    responses = [
        completed_process([]),
        completed_process(
            [
                {
                    "databaseId": 125,
                    "status": "in_progress",
                    "conclusion": None,
                    "url": "https://example.test/run/125",
                }
            ]
        ),
        completed_process(
            [
                {
                    "databaseId": 125,
                    "status": "completed",
                    "conclusion": "success",
                    "url": "https://example.test/run/125",
                }
            ]
        ),
    ]

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return responses.pop(0)

    monkeypatch.setattr(wait_ci.subprocess, "run", fake_run)
    clock = FakeClock()

    result = wait_ci.wait_for_matching_ci(
        repo="owner/repo",
        sha="abc123",
        timeout_seconds=60,
        poll_seconds=5,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result.status == "completed"
    assert clock.sleeps == [5, 5]

"""Tests for waiting on asynchronous GitHub commit statuses."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import wait_for_github_status as wait_status  # noqa: E402


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
    statuses: list[dict[str, object] | object],
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout=json.dumps({"statuses": statuses}),
        stderr="",
    )


def test_AC8_13_27_wait_returns_when_coveralls_unified_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: CI can wait for Coveralls unified success before passing."""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed_process(
            [
                {
                    "context": "Coveralls - unified",
                    "state": "success",
                    "description": "Coverage remained the same at 92.354%",
                    "target_url": "https://coveralls.io/jobs/1",
                }
            ]
        )

    monkeypatch.setattr(wait_status.subprocess, "run", fake_run)
    clock = FakeClock()

    result = wait_status.wait_for_status_success(
        repo="owner/repo",
        sha="abc123",
        context="Coveralls - unified",
        timeout_seconds=60,
        poll_seconds=5,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result.state == "success"
    assert result.target_url == "https://coveralls.io/jobs/1"
    assert calls == [["gh", "api", "repos/owner/repo/commits/abc123/status"]]
    assert clock.sleeps == []


def test_AC8_13_27_wait_fails_closed_on_coveralls_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: A failed Coveralls unified status fails the CI job."""

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return completed_process(
            [
                {
                    "context": "Coveralls - unified",
                    "state": "failure",
                    "description": "Coverage decreased (-0.08%) to 92.354%",
                    "target_url": "https://coveralls.io/jobs/2",
                }
            ]
        )

    monkeypatch.setattr(wait_status.subprocess, "run", fake_run)
    clock = FakeClock()

    with pytest.raises(RuntimeError, match="Coveralls - unified failed"):
        wait_status.wait_for_status_success(
            repo="owner/repo",
            sha="def456",
            context="Coveralls - unified",
            timeout_seconds=60,
            poll_seconds=5,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )


def test_AC8_13_27_wait_confirms_coveralls_failure_before_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: Confirmed Coveralls failures still fail after a re-poll."""
    responses = [
        completed_process(
            [
                {
                    "context": "Coveralls - unified",
                    "state": "failure",
                    "description": "Coverage decreased (-0.02%) to 92.335%",
                    "target_url": "https://coveralls.io/jobs/4",
                }
            ]
        ),
        completed_process(
            [
                {
                    "context": "Coveralls - unified",
                    "state": "failure",
                    "description": "Coverage decreased (-0.02%) to 92.335%",
                    "target_url": "https://coveralls.io/jobs/4",
                }
            ]
        ),
    ]

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return responses.pop(0)

    monkeypatch.setattr(wait_status.subprocess, "run", fake_run)
    clock = FakeClock()

    with pytest.raises(RuntimeError, match="Coverage decreased"):
        wait_status.wait_for_status_success(
            repo="owner/repo",
            sha="def456",
            context="Coveralls - unified",
            timeout_seconds=60,
            poll_seconds=5,
            failure_confirmation_seconds=15,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert clock.sleeps == [15]


def test_AC8_13_27_wait_allows_transient_coveralls_failure_to_recover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: A transient external failure does not fail if it recovers."""
    responses = [
        completed_process(
            [
                {
                    "context": "Coveralls - unified",
                    "state": "failure",
                    "description": "temporary processing error",
                    "target_url": "https://coveralls.io/jobs/5",
                }
            ]
        ),
        completed_process(
            [
                {
                    "context": "Coveralls - unified",
                    "state": "success",
                    "description": "Coverage remained the same",
                    "target_url": "https://coveralls.io/jobs/5",
                }
            ]
        ),
    ]

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return responses.pop(0)

    monkeypatch.setattr(wait_status.subprocess, "run", fake_run)
    clock = FakeClock()

    status = wait_status.wait_for_status_success(
        repo="owner/repo",
        sha="abc123",
        context="Coveralls - unified",
        timeout_seconds=60,
        poll_seconds=5,
        failure_confirmation_seconds=15,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert status.state == "success"
    assert clock.sleeps == [15]


def test_AC8_13_27_wait_reconfirms_failure_after_nonterminal_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: A later failure is confirmed again after pending status."""
    responses = [
        completed_process(
            [
                {
                    "context": "Coveralls - unified",
                    "state": "failure",
                    "description": "temporary processing error",
                    "target_url": "https://coveralls.io/jobs/7",
                }
            ]
        ),
        completed_process(
            [
                {
                    "context": "Coveralls - unified",
                    "state": "pending",
                    "description": "Coverage is being processed",
                    "target_url": "https://coveralls.io/jobs/7",
                }
            ]
        ),
        completed_process(
            [
                {
                    "context": "Coveralls - unified",
                    "state": "failure",
                    "description": "Coverage decreased (-0.02%) to 92.335%",
                    "target_url": "https://coveralls.io/jobs/7",
                }
            ]
        ),
        completed_process(
            [
                {
                    "context": "Coveralls - unified",
                    "state": "failure",
                    "description": "Coverage decreased (-0.02%) to 92.335%",
                    "target_url": "https://coveralls.io/jobs/7",
                }
            ]
        ),
    ]

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return responses.pop(0)

    monkeypatch.setattr(wait_status.subprocess, "run", fake_run)
    clock = FakeClock()

    with pytest.raises(RuntimeError, match="Coverage decreased"):
        wait_status.wait_for_status_success(
            repo="owner/repo",
            sha="abc123",
            context="Coveralls - unified",
            timeout_seconds=60,
            poll_seconds=5,
            failure_confirmation_seconds=15,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert clock.sleeps == [15, 5, 15]


def test_AC8_13_27_wait_polls_until_status_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: CI waits for Coveralls to write the asynchronous status."""
    responses = [
        completed_process([]),
        completed_process(
            [
                {
                    "context": "Coveralls - unified",
                    "state": "pending",
                    "description": "Coverage is being processed",
                    "target_url": "https://coveralls.io/jobs/3",
                }
            ]
        ),
        completed_process(
            [
                {
                    "context": "Coveralls - unified",
                    "state": "success",
                    "description": "Coverage passed",
                    "target_url": "https://coveralls.io/jobs/3",
                }
            ]
        ),
    ]

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return responses.pop(0)

    monkeypatch.setattr(wait_status.subprocess, "run", fake_run)
    clock = FakeClock()

    result = wait_status.wait_for_status_success(
        repo="owner/repo",
        sha="abc123",
        context="Coveralls - unified",
        timeout_seconds=60,
        poll_seconds=5,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result.state == "success"
    assert clock.sleeps == [5, 5]


def test_AC8_13_27_wait_times_out_when_status_never_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: Missing external statuses do not pass silently."""

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return completed_process([])

    monkeypatch.setattr(wait_status.subprocess, "run", fake_run)
    clock = FakeClock()

    with pytest.raises(TimeoutError, match="Timed out waiting"):
        wait_status.wait_for_status_success(
            repo="owner/repo",
            sha="abc123",
            context="Coveralls - unified",
            timeout_seconds=10,
            poll_seconds=5,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert clock.sleeps == [5, 5]


def test_AC8_13_27_wait_fails_when_github_status_query_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: GitHub status API failures fail closed."""

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="api unavailable",
        )

    monkeypatch.setattr(wait_status.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="failed to query GitHub commit statuses"):
        wait_status.wait_for_status_success(
            repo="owner/repo",
            sha="abc123",
            context="Coveralls - unified",
            timeout_seconds=1,
            poll_seconds=1,
        )


def test_AC8_13_27_wait_rejects_malformed_status_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: Unexpected GitHub status shapes fail closed."""

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps({"statuses": {"context": "Coveralls - unified"}}),
            stderr="",
        )

    monkeypatch.setattr(wait_status.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="did not contain a status list"):
        wait_status.wait_for_status_success(
            repo="owner/repo",
            sha="abc123",
            context="Coveralls - unified",
            timeout_seconds=1,
            poll_seconds=1,
        )


def test_AC8_13_27_wait_ignores_non_object_status_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: Non-object status entries cannot spoof success or failure."""

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return completed_process(
            [
                "bad-status",
                {
                    "context": "Coveralls - unified",
                    "state": "success",
                    "description": "Coverage passed",
                    "target_url": "https://coveralls.io/jobs/6",
                },
            ]
        )

    monkeypatch.setattr(wait_status.subprocess, "run", fake_run)

    status = wait_status.wait_for_status_success(
        repo="owner/repo",
        sha="abc123",
        context="Coveralls - unified",
        timeout_seconds=1,
        poll_seconds=1,
    )

    assert status.state == "success"

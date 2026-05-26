"""Tests for marking Coveralls aggregate status as reporting-only."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import mark_coveralls_reporting_status as marker  # noqa: E402


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
    payload: dict[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout=json.dumps(payload or {}),
        stderr="",
    )


def test_AC8_13_27_failed_coveralls_statuses_are_replaced_after_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: Coveralls status failures are reporting-only after local gate."""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ["gh", "api", "repos/owner/repo/commits/abc123/status"]:
            return completed_process(
                {
                    "statuses": [
                        {
                            "context": "coverage/coveralls",
                            "state": "failure",
                            "description": "Coverage decreased (-0.2%)",
                            "target_url": "https://coveralls.io/builds/1",
                        },
                        {
                            "context": "coverage/coveralls (push)",
                            "state": "failure",
                            "description": "Coverage decreased (-0.09%)",
                            "target_url": "https://coveralls.io/builds/2",
                        },
                        {
                            "context": "Coveralls - unified",
                            "state": "failure",
                            "description": "Coverage decreased (-0.08%)",
                            "target_url": "https://coveralls.io/jobs/1",
                        },
                        {
                            "context": "Coveralls - backend",
                            "state": "success",
                            "description": "Coverage remained the same",
                            "target_url": "https://coveralls.io/jobs/2",
                        },
                        {
                            "context": "Coveralls - frontend",
                            "state": "success",
                            "description": "Coverage remained the same",
                            "target_url": "https://coveralls.io/jobs/3",
                        },
                    ]
                }
            )
        return completed_process()

    monkeypatch.setattr(marker.subprocess, "run", fake_run)
    clock = FakeClock()

    observed = marker.mark_coveralls_reporting_only(
        repo="owner/repo",
        sha="abc123",
        target_url="https://github.com/owner/repo/actions/runs/9",
        timeout_seconds=30,
        poll_seconds=5,
        settle_seconds=0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert observed["coverage/coveralls"] is not None
    assert observed["coverage/coveralls"].state == "failure"
    assert observed["coverage/coveralls (push)"] is not None
    assert observed["coverage/coveralls (push)"].state == "failure"
    assert observed["Coveralls - unified"] is not None
    assert observed["Coveralls - unified"].state == "failure"
    post_calls = [call for call in calls if "--method" in call]
    assert len(post_calls) == 5
    assert post_calls[0] == [
        "gh",
        "api",
        "--method",
        "POST",
        "repos/owner/repo/statuses/abc123",
        "-f",
        "state=success",
        "-f",
        "context=coverage/coveralls",
        "-f",
        "description=Coveralls reporting-only; local coverage gate passed.",
        "-f",
        "target_url=https://github.com/owner/repo/actions/runs/9",
    ]
    assert post_calls[1][8] == "context=coverage/coveralls (push)"
    assert post_calls[2][8] == "context=Coveralls - unified"
    assert post_calls[3][8] == "context=Coveralls - backend"
    assert post_calls[4][8] == "context=Coveralls - frontend"
    assert clock.sleeps == []


def test_AC8_13_27_missing_coveralls_statuses_timeout_then_publish_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: Missing external statuses cannot leave PR CI pending."""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ["gh", "api", "repos/owner/repo/commits/def456/status"]:
            return completed_process({"statuses": []})
        return completed_process()

    monkeypatch.setattr(marker.subprocess, "run", fake_run)
    clock = FakeClock()

    observed = marker.mark_coveralls_reporting_only(
        repo="owner/repo",
        sha="def456",
        target_url="https://github.com/owner/repo/actions/runs/10",
        timeout_seconds=10,
        poll_seconds=5,
        settle_seconds=0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert observed == {
        "coverage/coveralls": None,
        "coverage/coveralls (push)": None,
        "Coveralls - unified": None,
        "Coveralls - backend": None,
        "Coveralls - frontend": None,
    }
    assert [call[:3] for call in calls].count(
        ["gh", "api", "repos/owner/repo/commits/def456/status"]
    ) == 3
    assert len([call for call in calls if "--method" in call]) == 5
    assert clock.sleeps == [5, 5]


def test_AC8_13_27_optional_coveralls_push_context_does_not_delay_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: Optional Coveralls contexts are normalized without blocking."""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ["gh", "api", "repos/owner/repo/commits/abc123/status"]:
            return completed_process(
                {
                    "statuses": [
                        {
                            "context": "coverage/coveralls",
                            "state": "success",
                            "description": "Coverage increased",
                            "target_url": "https://coveralls.io/builds/1",
                        },
                        {
                            "context": "Coveralls - unified",
                            "state": "success",
                            "description": "Coverage increased",
                            "target_url": "https://coveralls.io/jobs/1",
                        },
                        {
                            "context": "Coveralls - backend",
                            "state": "success",
                            "description": "Coverage remained the same",
                            "target_url": "https://coveralls.io/jobs/2",
                        },
                        {
                            "context": "Coveralls - frontend",
                            "state": "success",
                            "description": "Coverage remained the same",
                            "target_url": "https://coveralls.io/jobs/3",
                        },
                    ]
                }
            )
        return completed_process()

    monkeypatch.setattr(marker.subprocess, "run", fake_run)
    clock = FakeClock()

    observed = marker.mark_coveralls_reporting_only(
        repo="owner/repo",
        sha="abc123",
        target_url="https://github.com/owner/repo/actions/runs/9",
        timeout_seconds=120,
        poll_seconds=5,
        settle_seconds=0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert observed["coverage/coveralls"] is not None
    assert observed["coverage/coveralls (push)"] is None
    assert [call[:3] for call in calls].count(
        ["gh", "api", "repos/owner/repo/commits/abc123/status"]
    ) == 1
    assert len([call for call in calls if "--method" in call]) == 5
    assert clock.sleeps == []


def test_AC8_13_27_invalid_status_payload_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: Invalid GitHub status responses do not spoof success."""

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        assert args[:3] == ["gh", "api", "repos/owner/repo/commits/abc123/status"]
        return completed_process({"statuses": {"context": "coverage/coveralls"}})

    monkeypatch.setattr(marker.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="did not contain a list"):
        marker.wait_for_coveralls_observations(
            repo="owner/repo",
            sha="abc123",
            timeout_seconds=0,
        )


def test_AC8_13_27_late_coveralls_aggregate_failure_is_republished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: Late Coveralls aggregate writes cannot override reporting-only."""
    calls: list[list[str]] = []
    query_count = 0

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal query_count
        calls.append(args)
        if args[:3] == ["gh", "api", "repos/owner/repo/commits/abc123/status"]:
            query_count += 1
            if query_count == 1:
                return completed_process(
                    {
                        "statuses": [
                            {
                                "context": context,
                                "state": "success",
                                "description": "initial",
                                "target_url": "https://coveralls.io",
                            }
                            for context in marker.DEFAULT_CONTEXTS
                        ]
                    }
                )
            if query_count == 2:
                return completed_process(
                    {
                        "statuses": [
                            {
                                "context": "coverage/coveralls",
                                "state": "failure",
                                "description": "Coverage decreased later",
                                "target_url": "https://coveralls.io/builds/1",
                            },
                            {
                                "context": "coverage/coveralls (push)",
                                "state": "success",
                                "description": marker.DEFAULT_DESCRIPTION,
                                "target_url": "https://github.com/owner/repo/actions/runs/9",
                            },
                            {
                                "context": "Coveralls - unified",
                                "state": "success",
                                "description": marker.DEFAULT_DESCRIPTION,
                                "target_url": "https://github.com/owner/repo/actions/runs/9",
                            },
                            {
                                "context": "Coveralls - backend",
                                "state": "success",
                                "description": marker.DEFAULT_DESCRIPTION,
                                "target_url": "https://github.com/owner/repo/actions/runs/9",
                            },
                            {
                                "context": "Coveralls - frontend",
                                "state": "success",
                                "description": marker.DEFAULT_DESCRIPTION,
                                "target_url": "https://github.com/owner/repo/actions/runs/9",
                            },
                        ]
                    }
                )
            return completed_process(
                {
                    "statuses": [
                        {
                            "context": "coverage/coveralls",
                            "state": "success",
                            "description": marker.DEFAULT_DESCRIPTION,
                            "target_url": "https://github.com/owner/repo/actions/runs/9",
                        },
                        *[
                            {
                                "context": context,
                                "state": "success",
                                "description": marker.DEFAULT_DESCRIPTION,
                                "target_url": "https://github.com/owner/repo/actions/runs/9",
                            }
                            for context in marker.DEFAULT_CONTEXTS
                            if context != "coverage/coveralls"
                        ],
                    ]
                }
            )
        return completed_process()

    monkeypatch.setattr(marker.subprocess, "run", fake_run)
    clock = FakeClock()

    marker.mark_coveralls_reporting_only(
        repo="owner/repo",
        sha="abc123",
        target_url="https://github.com/owner/repo/actions/runs/9",
        timeout_seconds=30,
        poll_seconds=5,
        settle_seconds=45,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    post_calls = [call for call in calls if "--method" in call]
    assert len(post_calls) == 6
    assert post_calls[-1][8] == "context=coverage/coveralls"
    assert clock.sleeps == [45]


def test_AC8_13_27_discovered_coveralls_contexts_are_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.27: New Coveralls status context names are reporting-only too."""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ["gh", "api", "repos/owner/repo/commits/ghi789/status"]:
            return completed_process(
                {
                    "statuses": [
                        {
                            "context": "coverage/coveralls (matrix)",
                            "state": "failure",
                            "description": "Coverage decreased",
                            "target_url": "https://coveralls.io/builds/3",
                        },
                        *[
                            {
                                "context": context,
                                "state": "success",
                                "description": "initial",
                                "target_url": "https://coveralls.io",
                            }
                            for context in marker.DEFAULT_CONTEXTS
                        ],
                    ]
                }
            )
        return completed_process()

    monkeypatch.setattr(marker.subprocess, "run", fake_run)

    observed = marker.mark_coveralls_reporting_only(
        repo="owner/repo",
        sha="ghi789",
        target_url="https://github.com/owner/repo/actions/runs/11",
        timeout_seconds=0,
        settle_seconds=0,
    )

    assert observed["coverage/coveralls (matrix)"] is not None
    post_contexts = [call[8] for call in calls if "--method" in call]
    assert "context=coverage/coveralls (matrix)" in post_contexts

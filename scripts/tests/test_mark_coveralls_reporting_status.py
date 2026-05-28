"""Tests for publishing Coveralls reporting-only statuses."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import mark_coveralls_reporting_status as marker  # noqa: E402


def completed_process(
    payload: dict[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout=json.dumps(payload or {}),
        stderr="",
    )


def failed_process(stderr: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["gh"],
        returncode=1,
        stdout="",
        stderr=stderr,
    )


def post_contexts(calls: list[list[str]]) -> list[str]:
    return [call[8] for call in calls if "--method" in call]


def test_AC8_13_27_known_and_discovered_coveralls_contexts_are_reporting_only(
    monkeypatch,
) -> None:
    """AC8.13.27: Coveralls statuses are overwritten after local gates pass."""
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
                            "description": "Coverage decreased",
                            "target_url": "https://coveralls.io/builds/1",
                        },
                        {
                            "context": "coverage/coveralls (matrix)",
                            "state": "failure",
                            "description": "Coverage decreased",
                            "target_url": "https://coveralls.io/builds/2",
                        },
                        {
                            "context": "unrelated",
                            "state": "failure",
                            "description": "Not Coveralls",
                            "target_url": "https://example.com",
                        },
                    ]
                }
            )
        return completed_process()

    monkeypatch.setattr(marker.subprocess, "run", fake_run)

    contexts = marker.mark_coveralls_reporting_only(
        repo="owner/repo",
        sha="abc123",
        target_url="https://github.com/owner/repo/actions/runs/9",
    )

    assert contexts == (
        "coverage/coveralls",
        "coverage/coveralls (push)",
        "Coveralls - unified",
        "Coveralls - backend",
        "Coveralls - frontend",
        "coverage/coveralls (matrix)",
    )
    assert post_contexts(calls) == [
        "context=coverage/coveralls",
        "context=coverage/coveralls (push)",
        "context=Coveralls - unified",
        "context=Coveralls - backend",
        "context=Coveralls - frontend",
        "context=coverage/coveralls (matrix)",
    ]


def test_AC8_13_27_status_fetch_failure_still_publishes_known_contexts(
    monkeypatch,
) -> None:
    """AC8.13.27: GitHub status API flakiness cannot fail reporting-only CI."""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ["gh", "api", "repos/owner/repo/commits/main456/status"]:
            return failed_process("gh: HTTP 404")
        return completed_process()

    monkeypatch.setattr(marker.subprocess, "run", fake_run)

    contexts = marker.mark_coveralls_reporting_only(
        repo="owner/repo",
        sha="main456",
        target_url="https://github.com/owner/repo/actions/runs/13",
    )

    assert contexts == marker.DEFAULT_CONTEXTS
    assert post_contexts(calls) == [
        "context=coverage/coveralls",
        "context=coverage/coveralls (push)",
        "context=Coveralls - unified",
        "context=Coveralls - backend",
        "context=Coveralls - frontend",
    ]


def test_AC8_13_27_status_publish_failure_is_non_blocking(monkeypatch) -> None:
    """AC8.13.27: Coveralls status publication is telemetry, not a gate."""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ["gh", "api", "repos/owner/repo/commits/abc123/status"]:
            return completed_process({"statuses": []})
        if "--method" in args and args[8] == "context=Coveralls - unified":
            return failed_process("gh: HTTP 500")
        return completed_process()

    monkeypatch.setattr(marker.subprocess, "run", fake_run)

    contexts = marker.mark_coveralls_reporting_only(
        repo="owner/repo",
        sha="abc123",
        target_url="https://github.com/owner/repo/actions/runs/9",
    )

    assert contexts == marker.DEFAULT_CONTEXTS
    assert "context=Coveralls - unified" in post_contexts(calls)

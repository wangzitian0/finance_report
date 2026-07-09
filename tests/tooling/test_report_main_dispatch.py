"""Behavioral coverage for notify-infra2.yml's dispatch-SHA decision.

#1435 W1 / #1534 (AC8.13.146): replaces brittle `'dispatch_sha="${WORKFLOW_RUN_SHA:-}"'
in dispatch_script`-style bash-line-substring assertions (formerly in
test_AC8_13_146_report_main_dispatch_waits_for_ci_images in
test_post_merge_e2e_gates.py) with a real execution of
tools/_lib/shell/resolve_report_main_dispatch_sha.sh via subprocess, asserting
on its actual stdout/exit-code behavior. A harmless reformat of the script
(comments, whitespace, variable renaming) can no longer accidentally break
this coverage; only the actual dispatch/skip decision can.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "_lib"
    / "shell"
    / "resolve_report_main_dispatch_sha.sh"
)


def _run(
    event_name: str, workflow_run_sha: str, latest_main_sha: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), event_name, workflow_run_sha, latest_main_sha],
        capture_output=True,
        text=True,
    )


def test_AC8_13_146_manual_dispatch_always_targets_mains_current_tip() -> None:
    """A workflow_dispatch (manual re-trigger) always dispatches latest_main_sha, regardless of any stale workflow_run_sha value."""
    result = _run("workflow_dispatch", "", "deadbeef0000000000000000000000000000000")

    assert result.returncode == 0
    assert result.stdout.strip() == "deadbeef0000000000000000000000000000000"


def test_AC8_13_146_matching_workflow_run_sha_is_dispatched() -> None:
    """A completed CI run whose SHA IS main's current tip gets dispatched."""
    sha = "1111111111111111111111111111111111111a"
    result = _run("workflow_run", sha, sha)

    assert result.returncode == 0
    assert result.stdout.strip() == sha


def test_AC8_13_146_stale_workflow_run_completion_is_skipped_cleanly() -> None:
    """A CI run that finished AFTER a later push already moved main's tip is a stale completion — skip without dispatching, and exit 0 (not an error)."""
    result = _run(
        "workflow_run",
        "old0000000000000000000000000000000000000",
        "new1111111111111111111111111111111111111",
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""
    assert "Skipping stale CI completion" in result.stderr
    assert "old0000000000000000000000000000000000000" in result.stderr
    assert "new1111111111111111111111111111111111111" in result.stderr


def test_AC8_13_146_missing_workflow_run_sha_fails_closed() -> None:
    """A workflow_run event with no resolvable head SHA is a real error, not a skip — the caller must alert, not silently exit 0."""
    result = _run("workflow_run", "", "abc123")

    assert result.returncode == 1
    assert "No workflow_run head SHA resolved" in result.stderr

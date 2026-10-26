import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.testing import github_workflow_timing_summary as timing_summary  # noqa: E402

format_duration = timing_summary.format_duration
format_timing_summary = timing_summary.format_timing_summary
load_run = timing_summary.load_run
main = timing_summary.main
parse_github_time = timing_summary.parse_github_time


def test_AC8_13_34_parse_github_time_handles_empty_and_utc_values() -> None:
    assert parse_github_time(None) is None
    assert parse_github_time("") is None
    parsed = parse_github_time("2026-05-20T10:02:00Z")
    assert parsed is not None
    assert parsed.isoformat() == "2026-05-20T10:02:00+00:00"


def test_AC8_13_34_format_duration_uses_compact_minutes() -> None:
    """AC-testing.ci-structure.4: CI and post-merge workflows append queue, execution, and per-job timing summaries to GitHub Step Summary"""
    assert format_duration(None) == "n/a"
    assert format_duration(42) == "42s"
    assert format_duration(367) == "6m 7s"


def test_AC8_13_34_workflow_timing_summary_reports_queue_and_job_durations() -> None:
    run = {
        "url": "https://github.example/actions/runs/1",
        "createdAt": "2026-05-20T10:00:00Z",
        "updatedAt": "2026-05-20T10:08:30Z",
        "jobs": [
            {
                "name": "Classify Changes",
                "status": "completed",
                "conclusion": "success",
                "startedAt": "2026-05-20T10:02:00Z",
                "completedAt": "2026-05-20T10:02:04Z",
            },
            {
                "name": "Backend Tests (Shard 1/5)",
                "status": "completed",
                "conclusion": "success",
                "startedAt": "2026-05-20T10:02:10Z",
                "completedAt": "2026-05-20T10:07:20Z",
            },
        ],
    }

    summary = format_timing_summary(run, title="CI Timing Summary")

    assert "## CI Timing Summary" in summary
    assert "- Queue delay: `2m 0s`" in summary
    assert "- Execution window: `5m 20s`" in summary
    assert "- Run wall time: `7m 20s`" in summary
    assert "- Longest completed job: `Backend Tests (Shard 1/5)` at `5m 10s`" in summary
    assert "| `Classify Changes` | `success` | `4s` |" in summary


def test_AC8_13_34_workflow_timing_summary_handles_pending_jobs_without_completed_times() -> (
    None
):
    run = {
        "url": "https://github.example/actions/runs/2",
        "createdAt": "2026-05-20T10:00:00Z",
        "updatedAt": "2026-05-20T10:02:00Z",
        "jobs": [
            {
                "name": "Pending Backend",
                "status": "in_progress",
                "conclusion": None,
                "startedAt": "2026-05-20T10:01:00Z",
                "completedAt": None,
            },
            {
                "name": "Queued Backend",
                "status": "queued",
                "conclusion": None,
                "startedAt": None,
                "completedAt": None,
            },
        ],
    }

    summary = format_timing_summary(run, title="Partial Timing Summary")

    assert "- Queue delay: `1m 0s`" in summary
    assert "- Execution window: `1m 0s`" in summary
    assert "Longest completed job" not in summary
    assert (
        "| `Pending Backend` | `in_progress` | `n/a` | `2026-05-20T10:01:00Z` | `n/a` |"
        in summary
    )
    assert "| `Queued Backend` | `queued` | `n/a` | `n/a` | `n/a` |" in summary


def test_AC8_13_34_load_run_invokes_gh_run_view(monkeypatch) -> None:
    calls = []

    class Result:
        stdout = json.dumps(
            {"url": "https://github.example/actions/runs/3", "jobs": []}
        )

    def fake_run(args, *, check, text, capture_output):
        calls.append((args, check, text, capture_output))
        return Result()

    monkeypatch.setattr(timing_summary.subprocess, "run", fake_run)

    result = load_run("owner/repo", "123")

    assert result["url"] == "https://github.example/actions/runs/3"
    assert calls == [
        (
            [
                "gh",
                "run",
                "view",
                "123",
                "--repo",
                "owner/repo",
                "--json",
                "createdAt,updatedAt,jobs,url,status,conclusion",
            ],
            True,
            True,
            True,
        )
    ]


def test_AC8_13_34_main_appends_summary_file(monkeypatch, tmp_path) -> None:
    summary_path = tmp_path / "summary.md"

    monkeypatch.setattr(
        timing_summary,
        "load_run",
        lambda repo, run_id: {
            "url": f"https://github.example/{repo}/{run_id}",
            "createdAt": "2026-05-20T10:00:00Z",
            "updatedAt": "2026-05-20T10:00:05Z",
            "jobs": [],
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "github_workflow_timing_summary.py",
            "--repo",
            "owner/repo",
            "--run-id",
            "456",
            "--title",
            "Post-merge Timing Summary",
            "--summary-path",
            str(summary_path),
        ],
    )

    assert main() == 0

    content = summary_path.read_text(encoding="utf-8")
    assert "## Post-merge Timing Summary" in content
    assert "https://github.example/owner/repo/456" in content


# ---------------------------------------------------------------------------
# Pipeline budgets (#2688): the owner's PR, main and release time limits.
# ---------------------------------------------------------------------------

T0 = datetime(2026, 10, 26, 8, 0, 0, tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_taking(execution_seconds: int, *, queue_seconds: int = 0) -> dict:
    """A run whose first job starts after `queue_seconds` and whose last job ends
    `execution_seconds` later."""
    start = T0 + timedelta(seconds=queue_seconds)
    end = start + timedelta(seconds=execution_seconds)
    middle = start + timedelta(seconds=execution_seconds // 2)

    def job(name: str, began: datetime, ended: datetime) -> dict:
        return {
            "name": name,
            "status": "completed",
            "conclusion": "success",
            "startedAt": _iso(began),
            "completedAt": _iso(ended),
        }

    return {
        "url": "https://github.example/actions/runs/9",
        "createdAt": _iso(T0),
        "updatedAt": _iso(end),
        "jobs": [
            job("Fast", start, middle),
            job("Backend Tests (Shard 1/6)", start, end),
            job("Lint", start, start + timedelta(seconds=5)),
            job("Tooling", start, start + timedelta(seconds=9)),
        ],
    }


def _main_with(monkeypatch, tmp_path, run: dict, *flags: str) -> tuple[int, list, Path]:
    summary_path = tmp_path / "summary.md"
    gh_calls: list[list[str]] = []

    def fake_run(args, *, check, text, capture_output):
        gh_calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(timing_summary, "load_run", lambda repo, run_id: run)
    monkeypatch.setattr(timing_summary.subprocess, "run", fake_run)
    code = main(
        [
            "--repo",
            "owner/repo",
            "--run-id",
            "9",
            "--title",
            "Main CI Budget",
            "--summary-path",
            str(summary_path),
            *flags,
        ]
    )
    return code, gh_calls, summary_path


def test_pipeline_budgets_are_the_owner_limits() -> None:
    """PR checks 4 min, main regression 8 min, tag to staging-validated 15 min."""
    assert timing_summary.PIPELINE_BUDGET_SECONDS == {
        "pr": 240,
        "main": 480,
        "release": 900,
    }


@pytest.mark.parametrize(
    ("kind", "budget_seconds"), [("pr", 240), ("main", 480), ("release", 900)]
)
def test_budget_verdict_is_over_only_above_the_budget(
    kind: str, budget_seconds: int
) -> None:
    at_budget = timing_summary.budget_verdict(_run_taking(budget_seconds), kind)
    one_second_over = timing_summary.budget_verdict(
        _run_taking(budget_seconds + 1), kind
    )

    assert at_budget.exceeded is False
    assert one_second_over.exceeded is True
    assert one_second_over.budget_seconds == budget_seconds


def test_budget_verdict_ignores_queue_time() -> None:
    """A run that waited 20 minutes for a runner but executed in 3 is within `pr`."""
    verdict = timing_summary.budget_verdict(
        _run_taking(180, queue_seconds=20 * 60), "pr"
    )

    assert verdict.execution_seconds == 180
    assert verdict.exceeded is False


def test_summary_prints_the_budget_verdict_for_an_over_budget_run() -> None:
    over = format_timing_summary(
        _run_taking(9 * 60), title="Main CI Budget", budget_kind="main"
    )
    within = format_timing_summary(
        _run_taking(7 * 60), title="Main CI Budget", budget_kind="main"
    )
    plain = format_timing_summary(_run_taking(9 * 60), title="Main CI Budget")

    assert "- Budget `main`: execution window `9m 0s` of `8m 0s` (OVER)" in over
    assert "- Budget `main`: execution window `7m 0s` of `8m 0s` (within)" in within
    assert "- Budget `" not in plain


def test_enforce_fails_an_over_budget_run_and_comments_on_the_issue(
    monkeypatch, tmp_path
) -> None:
    code, gh_calls, summary_path = _main_with(
        monkeypatch,
        tmp_path,
        _run_taking(9 * 60),
        "--budget",
        "main",
        "--enforce",
        "--comment-issue",
        "2688",
    )

    assert code == 1
    assert len(gh_calls) == 1
    assert gh_calls[0][:6] == ["gh", "issue", "comment", "2688", "--repo", "owner/repo"]
    body = gh_calls[0][-1]
    assert "9m 0s" in body and "8m 0s" in body and "`main`" in body
    assert "https://github.example/actions/runs/9" in body
    # The three slowest jobs, slowest first; the 5 s Lint job is left out.
    assert body.index("Backend Tests (Shard 1/6)") < body.index("Fast")
    assert body.index("Fast") < body.index("Tooling")
    assert "Lint" not in body
    assert "(OVER)" in summary_path.read_text(encoding="utf-8")


def test_enforce_passes_a_run_within_budget_without_commenting(
    monkeypatch, tmp_path
) -> None:
    code, gh_calls, _ = _main_with(
        monkeypatch,
        tmp_path,
        _run_taking(7 * 60),
        "--budget",
        "main",
        "--enforce",
        "--comment-issue",
        "2688",
    )

    assert code == 0
    assert gh_calls == []


def test_a_pr_run_over_budget_only_prints(monkeypatch, tmp_path, capsys) -> None:
    code, gh_calls, summary_path = _main_with(
        monkeypatch, tmp_path, _run_taking(6 * 60), "--budget", "pr"
    )

    assert code == 0
    assert gh_calls == []
    assert "::warning::Pipeline budget exceeded" in capsys.readouterr().out
    assert "(OVER)" in summary_path.read_text(encoding="utf-8")


def test_enforce_fails_when_no_job_has_run(monkeypatch, tmp_path) -> None:
    empty = {"url": "u", "createdAt": _iso(T0), "updatedAt": _iso(T0), "jobs": []}

    enforced, _, _ = _main_with(
        monkeypatch, tmp_path, empty, "--budget", "release", "--enforce"
    )
    printed, _, _ = _main_with(monkeypatch, tmp_path, empty, "--budget", "release")

    assert enforced == 1
    assert printed == 0


def test_enforce_still_fails_when_the_issue_comment_fails(
    monkeypatch, tmp_path, capsys
) -> None:
    def failing_run(args, *, check, text, capture_output):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(
        timing_summary, "load_run", lambda repo, run_id: _run_taking(16 * 60)
    )
    monkeypatch.setattr(timing_summary.subprocess, "run", failing_run)

    code = main(
        [
            "--repo",
            "owner/repo",
            "--run-id",
            "9",
            "--summary-path",
            str(tmp_path / "summary.md"),
            "--budget",
            "release",
            "--enforce",
            "--comment-issue",
            "2688",
        ]
    )

    assert code == 1
    assert "::warning::Could not comment on issue 2688" in capsys.readouterr().out


def test_enforce_and_comment_need_a_budget(tmp_path) -> None:
    for flags in (["--enforce"], ["--comment-issue", "2688"]):
        with pytest.raises(SystemExit) as raised:
            main(
                [
                    "--repo",
                    "owner/repo",
                    "--run-id",
                    "9",
                    "--summary-path",
                    str(tmp_path / "summary.md"),
                    *flags,
                ]
            )
        assert raised.value.code == 2

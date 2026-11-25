"""Tests for common.testing.github_workflow_timing_summary."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path

import pytest
from infra2_sdk.manifests import CELL_POLICIES

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.testing import github_workflow_timing_summary as timing_summary

format_duration = timing_summary.format_duration
format_timing_summary = timing_summary.format_timing_summary
load_run = timing_summary.load_run
main = timing_summary.main
parse_github_time = timing_summary.parse_github_time

T0 = datetime(2026, 10, 26, 8, 0, 0, tzinfo=UTC)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _expected_budgets() -> dict[str, int]:
    return {
        "pr": CELL_POLICIES["ci.pre"].budget_seconds,
        "main": CELL_POLICIES["ci.post"].budget_seconds,
        "release": (
            CELL_POLICIES["staging.pre"].budget_seconds
            + CELL_POLICIES["staging.operation"].budget_seconds
            + CELL_POLICIES["staging.post"].budget_seconds
        ),
    }


def _run_taking(execution_seconds: int, *, queue_seconds: int = 0) -> dict:
    start = T0 + timedelta(seconds=queue_seconds)
    end = start + timedelta(seconds=execution_seconds)
    middle = start + timedelta(seconds=execution_seconds // 2)

    def _job(name: str, began: datetime, ended: datetime) -> dict:
        return {
            "name": name,
            "status": "completed",
            "conclusion": "success",
            "startedAt": _iso(began),
            "completedAt": _iso(ended),
        }

    return {
        "url": "https://github.example/actions/runs/9",
        "status": "completed",
        "conclusion": "success",
        "createdAt": _iso(T0),
        "updatedAt": _iso(end),
        "jobs": [
            _job("Fast", start, middle),
            _job("Backend Tests (Shard 1/6)", start, end),
            _job("Lint", start, start + timedelta(seconds=5)),
            _job("Tooling", start, start + timedelta(seconds=9)),
        ],
    }


def _main_with(
    monkeypatch,
    tmp_path: Path,
    run: dict,
    *flags: str,
    existing_comments: str = "",
    open_issue: str = "",
) -> tuple[int, list[list[str]], Path]:
    summary_path = tmp_path / "summary.md"
    gh_calls: list[list[str]] = []

    def fake_run(args, *, check, text, capture_output):
        if args[:3] == ["gh", "issue", "view"]:
            return subprocess.CompletedProcess(args, 0, stdout=existing_comments, stderr="")
        if args[:3] == ["gh", "issue", "list"]:
            gh_calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout=open_issue, stderr="")
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


def test_AC8_13_34_parse_github_time_handles_empty_and_utc_values() -> None:
    assert parse_github_time(None) is None
    assert parse_github_time("") is None
    parsed = parse_github_time("2026-05-20T10:02:00Z")
    assert parsed is not None
    assert parsed.isoformat() == "2026-05-20T10:02:00+00:00"


def test_AC8_13_34_format_duration_uses_compact_minutes() -> None:
    """AC-testing.ci-structure.4"""
    assert format_duration(None) == "n/a"
    assert format_duration(42) == "42s"
    assert format_duration(367) == "6m 7s"

    m1_run = {
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
    m1_summary = format_timing_summary(m1_run, title="CI Timing Summary")
    assert "## CI Timing Summary" in m1_summary
    assert "- Queue delay: `2m 0s`" in m1_summary
    assert "- Execution window: `5m 20s`" in m1_summary
    assert "- Run wall time: `7m 20s`" in m1_summary
    assert "- Longest completed job: `Backend Tests (Shard 1/5)` at `5m 10s`" in m1_summary
    assert "| `Classify Changes` | `success` | `4s` |" in m1_summary

    m2_run = {
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
    m2_summary = format_timing_summary(m2_run, title="Partial Timing Summary")
    assert "- Queue delay: `1m 0s`" in m2_summary
    assert "- Execution window: `1m 0s`" in m2_summary
    assert "Longest completed job" not in m2_summary
    assert (
        "| `Pending Backend` | `in_progress` | `n/a` | `2026-05-20T10:01:00Z` | `n/a` |"
        in m2_summary
    )
    assert "| `Queued Backend` | `queued` | `n/a` | `n/a` | `n/a` |" in m2_summary

    assert timing_summary.PIPELINE_BUDGET_SECONDS == _expected_budgets()
    m4_verdict = timing_summary.budget_verdict(
        _run_taking(180, queue_seconds=20 * 60), "pr"
    )
    assert m4_verdict.execution_seconds == 180
    assert m4_verdict.exceeded is False

    main_budget = timing_summary.PIPELINE_BUDGET_SECONDS["main"]
    m5_over = format_timing_summary(
        _run_taking(main_budget + 60), title="Main CI Budget", budget_kind="main"
    )
    m5_within = format_timing_summary(
        _run_taking(main_budget - 60), title="Main CI Budget", budget_kind="main"
    )
    m5_plain = format_timing_summary(
        _run_taking(main_budget + 60), title="Main CI Budget"
    )
    assert f"execution window `{format_duration(main_budget + 60)}` of `{format_duration(main_budget)}` (OVER)" in m5_over
    assert f"execution window `{format_duration(main_budget - 60)}` of `{format_duration(main_budget)}` (within)" in m5_within
    assert "- Budget `" not in m5_plain


def test_AC8_13_34_load_run_invokes_gh_run_view(monkeypatch) -> None:
    calls = []

    class Result:
        stdout = json.dumps({"url": "https://github.example/actions/runs/3", "jobs": []})

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


def test_AC8_13_34_main_appends_summary_file_and_writes_json_out(
    monkeypatch, tmp_path: Path
) -> None:
    summary_path = tmp_path / "summary.md"
    json_out = tmp_path / "nested" / "timing.json"
    monkeypatch.setattr(
        timing_summary,
        "load_run",
        lambda repo, run_id: {
            "url": f"https://github.example/{repo}/{run_id}",
            "status": "completed",
            "conclusion": "success",
            "createdAt": "2026-05-20T10:00:00Z",
            "updatedAt": "2026-05-20T10:00:05Z",
            "jobs": [
                {
                    "name": "Lint",
                    "status": "completed",
                    "conclusion": "success",
                    "startedAt": "2026-05-20T10:00:01Z",
                    "completedAt": "2026-05-20T10:00:05Z",
                }
            ],
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
            "--budget",
            "main",
            "--json-out",
            str(json_out),
        ],
    )
    assert main() == 0
    content = summary_path.read_text(encoding="utf-8")
    assert "## Post-merge Timing Summary" in content
    assert "https://github.example/owner/repo/456" in content

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["execution_seconds"] == 4
    assert payload["queue_seconds"] == 1
    assert payload["budget"]["kind"] == "main"
    assert payload["budget"]["budget_seconds"] == CELL_POLICIES["ci.post"].budget_seconds
    assert payload["budget"]["state"] == "within"
    assert len(payload["jobs"]) == 1 and payload["jobs"][0]["name"] == "Lint"


@pytest.mark.parametrize("kind", ("pr", "main", "release"))
def test_budget_verdict_is_over_only_above_the_budget(kind: str) -> None:
    expected = _expected_budgets()[kind]
    at_budget = timing_summary.budget_verdict(_run_taking(expected), kind)
    one_second_over = timing_summary.budget_verdict(_run_taking(expected + 1), kind)
    assert at_budget.exceeded is False
    assert one_second_over.exceeded is True
    assert one_second_over.budget_seconds == expected


def test_budget_numbers_have_one_machine_copy() -> None:
    root = Path(__file__).resolve().parents[2]
    docs = (root / "common/testing/ci-cd.md").read_text(encoding="utf-8") + (
        root / "common/runtime/ci-cd.md"
    ).read_text(encoding="utf-8")
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert timing_summary.PIPELINE_BUDGET_SECONDS == _expected_budgets()
    for text in (docs, workflow):
        assert not re.search(r"\b(240|480|780|900)\b|\b4 minutes?\b|\b8 minutes?\b", text)
    assert "Pipeline time contract" in docs
    assert "pipeline-budget" not in workflow + docs


def test_an_overrun_on_main_never_fails_and_opens_the_ci_budget_issue(
    monkeypatch, tmp_path: Path
) -> None:
    main_budget = timing_summary.PIPELINE_BUDGET_SECONDS["main"]
    over = main_budget + 60
    code, gh_calls, summary_path = _main_with(
        monkeypatch, tmp_path, _run_taking(over), "--budget", "main", "--comment"
    )
    assert code == 0
    create = [c for c in gh_calls if c[:3] == ["gh", "issue", "create"]]
    assert len(create) == 1
    assert create[0][create[0].index("--label") + 1] == "ci-budget"
    body = create[0][-1]
    assert format_duration(over) in body
    assert format_duration(main_budget) in body
    assert "`main`" in body
    assert "https://github.example/actions/runs/9" in body
    assert body.index("Backend Tests (Shard 1/6)") < body.index("Fast") < body.index("Tooling")
    assert "Lint" not in body
    assert "(OVER)" in summary_path.read_text(encoding="utf-8")


def test_an_overrun_on_main_updates_the_open_ci_budget_issue(
    monkeypatch, tmp_path: Path
) -> None:
    over = timing_summary.PIPELINE_BUDGET_SECONDS["main"] + 60
    code, gh_calls, _ = _main_with(
        monkeypatch,
        tmp_path,
        _run_taking(over),
        "--budget",
        "main",
        "--comment",
        open_issue="77\n",
    )
    assert code == 0
    assert [c for c in gh_calls if c[:3] == ["gh", "issue", "create"]] == []
    assert [c[:6] for c in gh_calls if c[:3] == ["gh", "issue", "comment"]] == [
        ["gh", "issue", "comment", "77", "--repo", "owner/repo"]
    ]


def test_a_pr_overrun_comments_on_the_pr(monkeypatch, tmp_path: Path) -> None:
    over = timing_summary.PIPELINE_BUDGET_SECONDS["pr"] + 60
    code, gh_calls, _ = _main_with(
        monkeypatch,
        tmp_path,
        _run_taking(over),
        "--budget",
        "pr",
        "--comment",
        "--pr",
        "12",
    )
    assert code == 0
    assert [c[:6] for c in gh_calls] == [
        ["gh", "issue", "comment", "12", "--repo", "owner/repo"]
    ]


def test_a_run_within_budget_reports_nothing(monkeypatch, tmp_path: Path) -> None:
    within = timing_summary.PIPELINE_BUDGET_SECONDS["main"] - 60
    code, gh_calls, _ = _main_with(
        monkeypatch, tmp_path, _run_taking(within), "--budget", "main", "--comment"
    )
    assert code == 0
    assert gh_calls == []


def test_a_run_that_cannot_be_measured_fails(monkeypatch, tmp_path: Path) -> None:
    empty = {"url": "u", "createdAt": _iso(T0), "updatedAt": _iso(T0), "jobs": []}
    budgeted, _, _ = _main_with(monkeypatch, tmp_path, empty, "--budget", "release")
    plain, _, _ = _main_with(monkeypatch, tmp_path, empty)
    assert budgeted == 1
    assert plain == 0


def test_a_failing_report_does_not_fail_the_run(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_run(args, *, check, text, capture_output):
        raise subprocess.CalledProcessError(1, args)

    over = timing_summary.PIPELINE_BUDGET_SECONDS["release"] + 60
    monkeypatch.setattr(timing_summary, "load_run", lambda repo, run_id: _run_taking(over))
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
            "--comment",
        ]
    )
    assert code == 0
    assert "::warning::Could not report the overrun" in capsys.readouterr().out


def test_comment_needs_a_budget_and_enforce_is_gone(tmp_path: Path) -> None:
    for flags in (["--enforce"], ["--comment"]):
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


def test_a_rerun_does_not_comment_twice_for_the_same_run(
    monkeypatch, tmp_path: Path
) -> None:
    over = timing_summary.PIPELINE_BUDGET_SECONDS["main"] + 60
    run = _run_taking(over)
    flags = ("--budget", "main", "--comment", "--pr", "5")
    _, first_calls, _ = _main_with(monkeypatch, tmp_path, run, *flags)
    _, again_calls, _ = _main_with(
        monkeypatch,
        tmp_path,
        run,
        *flags,
        existing_comments="Pipeline budget exceeded ... Run: " + run["url"],
    )
    _, other_calls, _ = _main_with(
        monkeypatch,
        tmp_path,
        run,
        *flags,
        existing_comments="Run: https://github.example/actions/runs/1",
    )
    _, longer_calls, _ = _main_with(
        monkeypatch,
        tmp_path,
        run,
        *flags,
        existing_comments="Run: https://github.example/actions/runs/90",
    )
    assert (len(first_calls), again_calls, len(other_calls), len(longer_calls)) == (
        1,
        [],
        1,
        1,
    )

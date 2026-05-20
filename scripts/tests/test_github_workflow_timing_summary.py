import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "github_workflow_timing_summary.py"
SPEC = importlib.util.spec_from_file_location("github_workflow_timing_summary", MODULE_PATH)
assert SPEC is not None
timing_summary = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["github_workflow_timing_summary"] = timing_summary
SPEC.loader.exec_module(timing_summary)

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
                "name": "Backend Tests (Shard 1/6)",
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
    assert "- Longest completed job: `Backend Tests (Shard 1/6)` at `5m 10s`" in summary
    assert "| `Classify Changes` | `success` | `4s` |" in summary


def test_AC8_13_34_workflow_timing_summary_handles_pending_jobs_without_completed_times() -> None:
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
    assert "| `Pending Backend` | `in_progress` | `n/a` | `2026-05-20T10:01:00Z` | `n/a` |" in summary
    assert "| `Queued Backend` | `queued` | `n/a` | `n/a` | `n/a` |" in summary


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

"""Observability, CI timing summary, CI post-telemetry, live quality board, and OpenPanel CLI."""

from __future__ import annotations

import argparse
import http.server
import io
import json
import re
import subprocess
import sys
import threading
import urllib.error
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from infra2_sdk.manifests import CELL_POLICIES, load_hooks_manifest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.observability import openpanel_query as op_cli  # noqa: E402
from common.testing import ci_telemetry  # noqa: E402
from common.testing import github_workflow_timing_summary as timing_summary  # noqa: E402
from common.testing import quality_board as qb  # noqa: E402

format_duration = timing_summary.format_duration
format_timing_summary = timing_summary.format_timing_summary
load_run = timing_summary.load_run
parse_github_time = timing_summary.parse_github_time

T0 = datetime(2026, 10, 26, 8, 0, 0, tzinfo=UTC)
BOARD_NOW = datetime(2026, 11, 25, 12, 0, 0, tzinfo=UTC)


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


def _timing_main_with(
    monkeypatch,
    tmp_path: Path,
    run: dict,
    *flags: str,
    existing_comments: str = "",
    open_issue: str = "",
) -> tuple[int, list[list[str]], Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    summary_path = tmp_path / "summary.md"
    gh_calls: list[list[str]] = []

    def fake_run(args, *, check, text, capture_output):
        if args[:3] == ["gh", "issue", "view"]:
            return subprocess.CompletedProcess(
                args, 0, stdout=existing_comments, stderr=""
            )
        if args[:3] == ["gh", "issue", "list"]:
            gh_calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout=open_issue, stderr="")
        gh_calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(timing_summary, "load_run", lambda repo, run_id: run)
    monkeypatch.setattr(timing_summary.subprocess, "run", fake_run)
    code = timing_summary.main(
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


def test_AC8_13_34_timing_summary_parsing_formatting_and_budgets(
    monkeypatch, tmp_path: Path
) -> None:
    """AC-testing.ci-structure.4"""
    assert parse_github_time(None) is None
    assert parse_github_time("") is None
    parsed = parse_github_time("2026-05-20T10:02:00Z")
    assert parsed is not None and parsed.isoformat() == "2026-05-20T10:02:00+00:00"

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
    assert (
        "- Longest completed job: `Backend Tests (Shard 1/5)` at `5m 10s`" in m1_summary
    )
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
    assert m4_verdict.execution_seconds == 180 and m4_verdict.exceeded is False

    main_budget = timing_summary.PIPELINE_BUDGET_SECONDS["main"]
    assert (
        f"execution window `{format_duration(main_budget + 60)}` of `{format_duration(main_budget)}` (OVER)"
        in format_timing_summary(
            _run_taking(main_budget + 60), title="Main CI Budget", budget_kind="main"
        )
    )
    assert (
        f"execution window `{format_duration(main_budget - 60)}` of `{format_duration(main_budget)}` (within)"
        in format_timing_summary(
            _run_taking(main_budget - 60), title="Main CI Budget", budget_kind="main"
        )
    )
    assert "- Budget `" not in format_timing_summary(
        _run_taking(main_budget + 60), title="Main CI Budget"
    )

    calls = []

    class _RunResult:
        stdout = json.dumps(
            {"url": "https://github.example/actions/runs/3", "jobs": []}
        )

    def _fake_load(args, *, check, text, capture_output):
        calls.append((args, check, text, capture_output))
        return _RunResult()

    monkeypatch.setattr(timing_summary.subprocess, "run", _fake_load)
    assert (
        load_run("owner/repo", "123")["url"] == "https://github.example/actions/runs/3"
    )
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
    assert timing_summary.main() == 0
    assert "## Post-merge Timing Summary" in summary_path.read_text(encoding="utf-8")
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert (
        payload["schema_version"] == 1
        and payload["execution_seconds"] == 4
        and payload["queue_seconds"] == 1
    )
    assert payload["budget"]["kind"] == "main"
    assert (
        payload["budget"]["budget_seconds"] == CELL_POLICIES["ci.post"].budget_seconds
    )
    assert payload["budget"]["state"] == "within"
    assert len(payload["jobs"]) == 1 and payload["jobs"][0]["name"] == "Lint"


@pytest.mark.parametrize("kind", ("pr", "main", "release"))
def test_budget_verdict_is_over_only_above_the_budget(kind: str) -> None:
    expected = _expected_budgets()[kind]
    assert timing_summary.budget_verdict(_run_taking(expected), kind).exceeded is False
    over = timing_summary.budget_verdict(_run_taking(expected + 1), kind)
    assert over.exceeded is True and over.budget_seconds == expected


def test_budget_numbers_have_one_machine_copy_and_reporting_behavior(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    docs = (ROOT / "common/testing/ci-cd.md").read_text(encoding="utf-8") + (
        ROOT / "common/runtime/ci-cd.md"
    ).read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert timing_summary.PIPELINE_BUDGET_SECONDS == _expected_budgets()
    for text in (docs, workflow):
        assert not re.search(
            r"\b(240|480|780|900)\b|\b4 minutes?\b|\b8 minutes?\b", text
        )
    assert "Pipeline time contract" in docs and "pipeline-budget" not in workflow + docs

    main_budget = timing_summary.PIPELINE_BUDGET_SECONDS["main"]
    over = main_budget + 60
    code, gh_calls, summary_path = _timing_main_with(
        monkeypatch,
        tmp_path / "create",
        _run_taking(over),
        "--budget",
        "main",
        "--comment",
    )
    assert code == 0
    create = [c for c in gh_calls if c[:3] == ["gh", "issue", "create"]]
    assert len(create) == 1 and create[0][create[0].index("--label") + 1] == "ci-budget"
    body = create[0][-1]
    assert format_duration(over) in body and format_duration(main_budget) in body
    assert (
        body.index("Backend Tests (Shard 1/6)")
        < body.index("Fast")
        < body.index("Tooling")
    )
    assert "Lint" not in body and "(OVER)" in summary_path.read_text(encoding="utf-8")

    code2, gh_calls2, _ = _timing_main_with(
        monkeypatch,
        tmp_path / "upd",
        _run_taking(over),
        "--budget",
        "main",
        "--comment",
        open_issue="77\n",
    )
    assert code2 == 0
    assert [c for c in gh_calls2 if c[:3] == ["gh", "issue", "create"]] == []
    assert [c[:6] for c in gh_calls2 if c[:3] == ["gh", "issue", "comment"]] == [
        ["gh", "issue", "comment", "77", "--repo", "owner/repo"]
    ]

    pr_over = timing_summary.PIPELINE_BUDGET_SECONDS["pr"] + 60
    code3, gh_calls3, _ = _timing_main_with(
        monkeypatch,
        tmp_path / "pr",
        _run_taking(pr_over),
        "--budget",
        "pr",
        "--comment",
        "--pr",
        "12",
    )
    assert code3 == 0 and [c[:6] for c in gh_calls3] == [
        ["gh", "issue", "comment", "12", "--repo", "owner/repo"]
    ]

    code4, gh_calls4, _ = _timing_main_with(
        monkeypatch,
        tmp_path / "within",
        _run_taking(main_budget - 60),
        "--budget",
        "main",
        "--comment",
    )
    assert code4 == 0 and gh_calls4 == []

    empty = {"url": "u", "createdAt": _iso(T0), "updatedAt": _iso(T0), "jobs": []}
    assert (
        _timing_main_with(
            monkeypatch, tmp_path / "empty_b", empty, "--budget", "release"
        )[0]
        == 1
    )
    assert _timing_main_with(monkeypatch, tmp_path / "empty_p", empty)[0] == 0

    def _failing_gh(args, *, check, text, capture_output):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(
        timing_summary,
        "load_run",
        lambda repo, run_id: _run_taking(
            timing_summary.PIPELINE_BUDGET_SECONDS["release"] + 60
        ),
    )
    monkeypatch.setattr(timing_summary.subprocess, "run", _failing_gh)
    assert (
        timing_summary.main(
            [
                "--repo",
                "owner/repo",
                "--run-id",
                "9",
                "--summary-path",
                str(tmp_path / "fail_sum.md"),
                "--budget",
                "release",
                "--comment",
            ]
        )
        == 0
    )
    assert "::warning::Could not report the overrun" in capsys.readouterr().out

    for flags in (["--enforce"], ["--comment"]):
        with pytest.raises(SystemExit) as raised:
            timing_summary.main(
                [
                    "--repo",
                    "owner/repo",
                    "--run-id",
                    "9",
                    "--summary-path",
                    str(tmp_path / "s.md"),
                    *flags,
                ]
            )
        assert raised.value.code == 2

    run = _run_taking(over)
    flags = ("--budget", "main", "--comment", "--pr", "5")
    assert len(_timing_main_with(monkeypatch, tmp_path / "r1", run, *flags)[1]) == 1
    assert (
        _timing_main_with(
            monkeypatch,
            tmp_path / "r2",
            run,
            *flags,
            existing_comments="Run: " + run["url"],
        )[1]
        == []
    )
    assert (
        len(
            _timing_main_with(
                monkeypatch,
                tmp_path / "r3",
                run,
                *flags,
                existing_comments="Run: https://github.example/actions/runs/1",
            )[1]
        )
        == 1
    )
    assert (
        len(
            _timing_main_with(
                monkeypatch,
                tmp_path / "r4",
                run,
                *flags,
                existing_comments="Run: https://github.example/actions/runs/90",
            )[1]
        )
        == 1
    )


def test_ci_telemetry_payload_cli_and_non_blocking_coverage_metrics(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = ci_telemetry.build_ci_telemetry_payload(
        sha="deadbeef" * 5,
        ref="refs/heads/main",
        event_name="push",
        run_id="999",
        run_url="https://github.com/o/r/actions/runs/999",
        timing={
            "execution_seconds": 310,
            "budget": {"kind": "main", "state": "within"},
        },
        backend_coverage={
            "totals": {
                "percent_covered": 96.4321,
                "covered_lines": 9643,
                "num_statements": 10000,
                "missing_lines": 357,
            }
        },
        frontend_coverage={
            "total": {
                "lines": {"pct": 98.12},
                "statements": {"pct": 98.05},
                "functions": {"pct": 98.5},
                "branches": {"pct": 85.4},
            }
        },
        needs={
            "lint": {"result": "success"},
            "backend": {"result": "success"},
            "frontend-vitest": {"result": "skipped"},
        },
        generated_at_utc="2026-11-25T05:00:00Z",
    )
    assert (
        payload["schema_version"] == 1 and payload["timing"]["execution_seconds"] == 310
    )
    assert payload["coverage"]["backend"] == {
        "percent_covered": 96.43,
        "covered_lines": 9643,
        "num_statements": 10000,
        "missing_lines": 357,
    }
    assert payload["jobs"] == {
        "backend": "success",
        "frontend-vitest": "skipped",
        "lint": "success",
    }

    corrupt_be = tmp_path / "be.json"
    corrupt_be.write_text("{bad json", encoding="utf-8")
    fe_summary = tmp_path / "fe.json"
    fe_summary.write_text(
        json.dumps(
            {
                "total": {
                    "lines": {"pct": 98.2},
                    "statements": {"pct": 98.1},
                    "functions": {"pct": 98.3},
                    "branches": {"pct": 84.9},
                }
            }
        ),
        encoding="utf-8",
    )
    out_file = tmp_path / "out/ci-post-telemetry.json"
    monkeypatch.setenv("TEST_NEEDS", json.dumps({"lint": {"result": "success"}}))
    assert (
        ci_telemetry.main(
            [
                "--timing-json",
                str(tmp_path / "missing.json"),
                "--backend-coverage-json",
                str(corrupt_be),
                "--frontend-coverage-json",
                str(fe_summary),
                "--needs-json-env",
                "TEST_NEEDS",
                "--sha",
                "abc1234",
                "--ref",
                "refs/heads/main",
                "--event-name",
                "push",
                "--run-id",
                "42",
                "--run-url",
                "https://github.com/o/r/actions/runs/42",
                "--output",
                str(out_file),
            ]
        )
        == 0
    )
    assert "ignoring unreadable telemetry JSON" in capsys.readouterr().err
    written = json.loads(out_file.read_text(encoding="utf-8"))
    assert written["timing"] is None and written["coverage"]["backend"] is None
    assert written["coverage"]["frontend"]["lines_pct"] == 98.2

    ci_yml = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "--fail-under=" not in ci_yml
    assert (
        "coverage-backend-summary.json" in ci_yml
        and "name: ci-coverage-backend" in ci_yml
    )
    vitest_cfg = (ROOT / "apps/frontend/vitest.config.ts").read_text(encoding="utf-8")
    assert "thresholds:" not in vitest_cfg and "'json-summary'" in vitest_cfg
    assert not (ROOT / "apps/frontend/src/__tests__/coverageBaseline.test.ts").exists()


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class _FakeResp:
    def __init__(self, payload: bytes, *, status: int = 200) -> None:
        self._payload = payload
        self.status = status
        self.headers: dict[str, str] = {}

    def read(self) -> bytes:
        return self._payload

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_a: object) -> bool:
        return False


def test_quality_board_freshness_security_hardening_and_rendering(
    tmp_path: Path,
) -> None:
    manifest_path = ROOT / "runtime-hooks.manifest.json"
    sdk_ids = [
        c.id
        for c in load_hooks_manifest(manifest_path).checks_for_cell("scheduled_audit")
    ]
    assert list(qb.expected_scheduled_audit_checks(manifest_path)) == sdk_ids

    healthy_pair = {
        "staging": {"reachable": True, "status": "healthy"},
        "production": {"reachable": True, "status": "healthy"},
    }
    fresh_ci = {
        "artifacts_count": 1,
        "latest_at_utc": qb.format_utc(BOARD_NOW - timedelta(hours=2)),
    }
    fresh_audit = {
        "artifacts_count": 1,
        "latest_at_utc": qb.format_utc(BOARD_NOW - timedelta(hours=4)),
        "completeness": {"completed": 4, "expected": 4},
        "latest": {"status": "pass"},
    }
    assert (
        qb.compute_freshness(
            now=BOARD_NOW,
            ci_post=fresh_ci,
            scheduled_audit=fresh_audit,
            runtime_health=healthy_pair,
        )["status"]
        == "FRESH"
    )
    assert (
        qb.compute_freshness(
            now=BOARD_NOW,
            ci_post=fresh_ci,
            scheduled_audit={
                **fresh_audit,
                "completeness": {"completed": 2, "expected": 4},
            },
            runtime_health=healthy_pair,
        )["status"]
        == "STALE_WARN"
    )
    assert (
        qb.compute_freshness(
            now=BOARD_NOW,
            ci_post=fresh_ci,
            scheduled_audit={
                "artifacts_count": 0,
                "latest_at_utc": None,
                "completeness": {"completed": 0, "expected": 4},
                "latest": None,
            },
            runtime_health=healthy_pair,
        )["status"]
        == "STALE_CRITICAL"
    )
    assert (
        qb.compute_freshness(
            now=BOARD_NOW,
            ci_post=fresh_ci,
            scheduled_audit={
                **fresh_audit,
                "latest_at_utc": qb.format_utc(BOARD_NOW - timedelta(hours=73)),
            },
            runtime_health=healthy_pair,
        )["status"]
        == "STALE_CRITICAL"
    )
    assert (
        qb.compute_freshness(
            now=BOARD_NOW,
            ci_post=fresh_ci,
            scheduled_audit=fresh_audit,
            runtime_health={
                "staging": {"reachable": False, "status": "error"},
                "production": {"reachable": False, "status": "error"},
            },
        )["status"]
        == "STALE_CRITICAL"
    )

    # Hardening check: ci_count > 0 with unparseable/missing latest_at_utc warns instead of silently staying FRESH
    unparseable_ci = qb.compute_freshness(
        now=BOARD_NOW,
        ci_post={"artifacts_count": 2, "latest_at_utc": "not-a-timestamp"},
        scheduled_audit=fresh_audit,
        runtime_health=healthy_pair,
    )
    assert unparseable_ci["status"] == "STALE_WARN"
    assert any("missing or unparseable" in r for r in unparseable_ci["reasons"])

    # Hardening checks on render_html: safe HTTP URLs, pre-escape slicing of oracle_summaries, numeric duration guard
    long_oracle = {"note": ("a" * 165) + "<<<<>>>>&&&&"}
    rendered = qb.render_html(
        {
            "generated_at_utc": "2026-11-25T12:00:00Z",
            "generated_at_utc8": "2026-11-25 20:00:00 UTC+8",
            "freshness": {"status": "FRESH", "reasons": []},
            "runtime_health": healthy_pair,
            "scheduled_audit": {
                "completeness": {"completed": 1, "expected": 1},
                "runs": [
                    {
                        "run_url": "javascript:alert(1)",
                        "run_id": "10",
                        "created_at": "2026-11-25T10:00:00Z",
                        "version_ref": "main",
                        "status": "pass",
                        "completed_checks": 1,
                        "expected_checks": 1,
                        "checks": [],
                        "oracle_summaries": long_oracle,
                    }
                ],
                "fallback_audit_runs": [
                    {
                        "run_url": "data:text/html,xss",
                        "run_id": "11",
                        "conclusion": "success",
                    }
                ],
            },
            "ci_post": {
                "runs": [
                    {
                        "run_url": "javascript:evil()",
                        "sha": "abc",
                        "execution_seconds": "bad",
                        "budget_seconds": 480,
                        "budget_state": "within",
                    },
                    {
                        "run_url": "https://github.com/o/r/actions/runs/4",
                        "sha": "bools",
                        "execution_seconds": True,
                        "budget_seconds": True,
                        "budget_state": "within",
                    },
                    {
                        "run_url": "https://github.com/o/r/actions/runs/5",
                        "sha": "def",
                        "execution_seconds": 100,
                        "budget_seconds": 0,
                        "budget_state": "within",
                    },
                ]
            },
            "user_cases": {"domains": []},
        }
    )
    assert "javascript:" not in rendered
    assert "data:text/html" not in rendered
    assert (
        'href="#"' in rendered
        and 'href="https://github.com/o/r/actions/runs/5"' in rendered
    )
    assert rendered.count('<td class="num">n/a</td>') >= 3
    assert "Trues" not in rendered
    # Pre-escape slicing preserves well-formed entities even when truncation cuts across '&' / '<'
    mono_match = re.search(r'<td class="mono">(.*?)</td>', rendered)
    assert mono_match and not re.search(r"&[a-z]+$", mono_match.group(1))

    # Auth header stripped on HTTP redirect when downloading artifact zip
    seen_headers: list[tuple[str, str | None]] = []
    zip_payload = _zip_bytes({"hello.json": b'{"ok": true}'})

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen_headers.append((self.path, self.headers.get("Authorization")))
            if self.path == "/artifact.zip":
                self.send_response(302)
                self.send_header(
                    "Location", f"http://127.0.0.1:{self.server.server_port}/signed.zip"
                )
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(zip_payload)))
            self.end_headers()
            self.wfile.write(zip_payload)

        def log_message(self, *_args: object) -> None:
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        files = qb.download_artifact_files(
            f"http://127.0.0.1:{server.server_port}/artifact.zip",
            token="ghp_secret_token",
        )
    finally:
        server.shutdown()
        server.server_close()
    assert files == {"hello.json": b'{"ok": true}'}
    assert seen_headers == [
        ("/artifact.zip", "Bearer ghp_secret_token"),
        ("/signed.zip", None),
    ]


def test_quality_board_write_dashboard_end_to_end(tmp_path: Path) -> None:
    ci_zip = _zip_bytes(
        {
            "ci-post-telemetry.json": json.dumps(
                {
                    "run_id": "101",
                    "run_url": "https://github.com/o/f/actions/runs/101",
                    "sha": "1234567890",
                    "ref": "refs/heads/main",
                    "generated_at_utc": qb.format_utc(BOARD_NOW - timedelta(hours=1)),
                    "timing": {
                        "execution_seconds": 210,
                        "budget": {"budget_seconds": 480, "state": "within"},
                    },
                    "coverage": {
                        "backend": {"percent_covered": 96.8},
                        "frontend": {"lines_pct": 98.4},
                    },
                    "jobs": {"lint": "success"},
                }
            ).encode("utf-8")
        }
    )
    audit_zip = _zip_bytes(
        {
            "scheduled-audit-result.json": json.dumps(
                {
                    "scheduled_audit_results": [
                        {
                            "service": "finance_report/app",
                            "version_ref": "v0.2.98",
                            "status": "pass",
                            "summary": "all 4 passed",
                            "duration_seconds": 320.0,
                            "checks": [
                                {"name": "audit_replay", "ok": True, "seconds": 80},
                                {"name": "core_journey", "ok": True, "seconds": 90},
                                {
                                    "name": "pdf_corpus_oracle",
                                    "ok": True,
                                    "seconds": 75,
                                },
                                {
                                    "name": "financial_scenario_benchmark",
                                    "ok": True,
                                    "seconds": 75,
                                },
                            ],
                            "oracle_summaries": {
                                "pdf_corpus_oracle_summary": {"passed": 8, "failed": 0}
                            },
                        }
                    ]
                }
            ).encode("utf-8")
        }
    )
    stage_zip = _zip_bytes(
        {
            "stage.json": json.dumps(
                {"env": "staging.provider_regression", "verdict": "pass"}
            ).encode("utf-8")
        }
    )

    def fake_opener(request: Any, _timeout: float) -> _FakeResp:
        url = request.full_url
        if "name=ci-post-telemetry" in url:
            return _FakeResp(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "id": 11,
                                "expired": False,
                                "created_at": qb.format_utc(
                                    BOARD_NOW - timedelta(hours=1)
                                ),
                                "archive_download_url": "https://api.github.com/ci.zip",
                                "workflow_run": {"id": 101, "head_branch": "main"},
                            }
                        ]
                    }
                ).encode("utf-8")
            )
        if url == "https://api.github.com/ci.zip":
            return _FakeResp(ci_zip)
        if "workflows/ci.yml/runs" in url or "reconcile-iac-inputs.yml/runs" in url:
            return _FakeResp(b'{"workflow_runs": []}')
        if "name=scheduled-audit-results" in url:
            return _FakeResp(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "id": 22,
                                "expired": False,
                                "created_at": qb.format_utc(
                                    BOARD_NOW - timedelta(hours=2)
                                ),
                                "archive_download_url": "https://api.github.com/audit.zip",
                                "workflow_run": {"id": 202},
                            }
                        ]
                    }
                ).encode("utf-8")
            )
        if url == "https://api.github.com/audit.zip":
            return _FakeResp(audit_zip)
        if "/actions/runs/202/artifacts" in url:
            return _FakeResp(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "id": 23,
                                "name": "stage-staging.provider_regression-post-sha-abc",
                                "expired": False,
                                "archive_download_url": "https://api.github.com/stage.zip",
                            }
                        ]
                    }
                ).encode("utf-8")
            )
        if url == "https://api.github.com/stage.zip":
            return _FakeResp(stage_zip)
        if "report-staging" in url:
            return _FakeResp(
                json.dumps(
                    {
                        "status": "healthy",
                        "version": "<script>alert(1)</script>",
                        "checks": {
                            "database": {
                                "status": "present",
                                "detail": "ok",
                                "duration_ms": 5,
                            }
                        },
                    }
                ).encode("utf-8")
            )
        if "report.zitian" in url:
            return _FakeResp(
                json.dumps(
                    {
                        "status": "healthy",
                        "version": "v0.2.95",
                        "checks": {
                            "market_data": {
                                "status": "present",
                                "detail": "ok",
                                "duration_ms": 9,
                            }
                        },
                    }
                ).encode("utf-8")
            )
        raise AssertionError(f"unexpected URL in fake_opener: {url}")

    out_dir = tmp_path / "board"
    data = qb.write_dashboard(
        output_dir=out_dir, repo_root=ROOT, opener=fake_opener, now=BOARD_NOW
    )
    assert data["freshness"]["status"] == "FRESH"
    assert data["freshness"]["completeness"] == {"completed": 4, "expected": 4}
    assert data["user_cases"]["total"] == 47
    assert data["scheduled_audit"]["runs"][0]["stage_record_verdict"] == "pass"

    html_text = (out_dir / "index.html").read_text(encoding="utf-8")
    assert "Freshness Heartbeat: FRESH" in html_text
    assert "2026-11-25 20:00:00 UTC+8" in html_text
    assert "2026-11-25T12:00:00Z" in html_text
    assert "Nightly Completeness: <strong>4/4</strong>" in html_text
    assert "<script>alert(1)</script>" not in html_text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_text


def test_AC23_1_4_openpanel_query_cli_payloads_security_and_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-observability.openpanel-query.1 AC24.1.4"""
    parser = op_cli.build_parser()
    assert isinstance(parser, argparse.ArgumentParser)
    with pytest.raises(SystemExit) as help_exc:
        parser.parse_args(["--help"])
    assert help_exc.value.code == 0
    assert "--api-key" not in parser.format_help()

    assert op_cli.resolve_api_key({"OPENPANEL_API_KEY": "abc"}) == "abc"
    with pytest.raises(SystemExit):
        op_cli.resolve_api_key({})

    events_ns = argparse.Namespace(
        command="events", env="staging", limit=50, event="upload_clicked", api_url=None
    )
    assert op_cli.build_payload(events_ns) == {
        "event": "upload_clicked",
        "limit": 50,
        "filters": [{"name": "environment", "operator": "is", "value": ["staging"]}],
    }
    funnel_ns = argparse.Namespace(
        command="funnel", env=None, limit=10, steps="a, b , ,c", api_url=None
    )
    funnel_payload = op_cli.build_payload(funnel_ns)
    assert (
        funnel_payload["steps"] == ["a", "b", "c"] and "filters" not in funnel_payload
    )

    monkeypatch.setenv("OPENPANEL_API_KEY", "secret-key")
    captured: dict[str, object] = {}

    def _fake_transport(
        url: str, key: str, payload: dict[str, object]
    ) -> dict[str, object]:
        captured.update({"url": url, "key": key, "payload": payload})
        return {"ok": True}

    run_ns = argparse.Namespace(
        command="events",
        env="production",
        limit=5,
        event=None,
        api_url="https://op.example/api/",
    )
    assert op_cli.run(run_ns, transport=_fake_transport) == {"ok": True}
    assert (
        captured["url"] == "https://op.example/api/events"
        and captured["key"] == "secret-key"
    )

    monkeypatch.delenv("OPENPANEL_API_URL", raising=False)
    assert op_cli.resolve_api_url(None) == op_cli.DEFAULT_API_URL
    monkeypatch.setenv("OPENPANEL_API_URL", "https://env.example/api")
    assert op_cli.resolve_api_url(None) == "https://env.example/api"
    assert (
        op_cli.resolve_api_url("https://flag.example/api") == "https://flag.example/api"
    )
    assert (
        op_cli.resolve_api_url("http://localhost:3000/api")
        == "http://localhost:3000/api"
    )
    assert op_cli.resolve_api_url("http://127.0.0.1/api") == "http://127.0.0.1/api"
    for bad_url in ("http://op.example.com/api", "ftp://op.example.com/api"):
        with pytest.raises(SystemExit):
            op_cli.resolve_api_url(bad_url)

    monkeypatch.setattr(
        op_cli, "post_json", lambda url, key, payload: {"events": [], "url": url}
    )
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    assert op_cli.main(["--env", "staging", "events"]) == 0
    assert json.loads(out.getvalue())["url"].endswith("/events")

    def _boom(url: str, key: str, payload: dict[str, object]) -> dict[str, object]:
        raise urllib.error.URLError("down")

    monkeypatch.setattr(op_cli, "post_json", _boom)
    err = io.StringIO()
    monkeypatch.setattr("sys.stderr", err)
    assert op_cli.main(["funnel", "--steps", "a,b"]) == 1 and "failed" in err.getvalue()

    preset_ns = argparse.Namespace(
        command="funnel",
        env="production",
        limit=100,
        steps=None,
        preset="core-funnel",
        api_url=None,
    )
    assert op_cli.build_payload(preset_ns)["steps"] == [
        "upload_started",
        "upload_succeeded",
        "review_approved",
        "report_generated",
    ]
    with pytest.raises(SystemExit):
        op_cli.resolve_funnel_steps(argparse.Namespace(steps="only_one", preset=None))
    with pytest.raises(SystemExit):
        op_cli.resolve_funnel_steps(
            argparse.Namespace(steps=None, preset="unknown-preset")
        )

    monkeypatch.setattr(
        op_cli,
        "post_json",
        lambda url, key, payload: {
            "steps": [
                {"event": "upload_started", "count": 20},
                {"event": "upload_succeeded", "count": 15},
                {"event": "review_approved", "count": 12},
                {"event": "report_generated", "count": 10},
            ]
        },
    )
    out_md = io.StringIO()
    monkeypatch.setattr("sys.stdout", out_md)
    assert (
        op_cli.main(
            [
                "--env",
                "production",
                "--format",
                "markdown",
                "funnel",
                "--preset",
                "core-funnel",
            ]
        )
        == 0
    )
    md = out_md.getvalue()
    assert "### OpenPanel Funnel Summary (production)" in md
    assert "| 1 | `upload_started` | 20 | 100.0% |" in md
    assert "| 4 | `report_generated` | 10 | 50.0% |" in md

    out_events = io.StringIO()
    monkeypatch.setattr("sys.stdout", out_events)
    monkeypatch.setattr(
        op_cli,
        "post_json",
        lambda url, key, payload: {"events": [{"id": 1}, {"id": 2}]},
    )
    assert op_cli.main(["--env", "staging", "--format", "markdown", "events"]) == 0
    assert "Total returned: 2" in out_events.getvalue()
    assert "| 1 |" not in op_cli.format_markdown_summary(
        {"steps": ["not-a-dict"]}, command="funnel"
    )
    assert "(no funnel steps returned)" in op_cli.format_markdown_summary(
        {"steps": []}, command="funnel"
    )

"""Tests for common.testing.ci_telemetry (#3215 Slice 2B)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.testing import ci_telemetry


def test_build_ci_telemetry_payload_extracts_timing_coverage_and_jobs() -> None:
    payload = ci_telemetry.build_ci_telemetry_payload(
        sha="deadbeef" * 5,
        ref="refs/heads/main",
        event_name="push",
        run_id="999",
        run_url="https://github.com/o/r/actions/runs/999",
        timing={"execution_seconds": 310, "budget": {"kind": "main", "state": "within"}},
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
    assert payload["schema_version"] == 1
    assert payload["generated_at_utc"] == "2026-11-25T05:00:00Z"
    assert payload["timing"]["execution_seconds"] == 310
    assert payload["coverage"]["backend"] == {
        "percent_covered": 96.43,
        "covered_lines": 9643,
        "num_statements": 10000,
        "missing_lines": 357,
    }
    assert payload["coverage"]["frontend"] == {
        "lines_pct": 98.12,
        "statements_pct": 98.05,
        "functions_pct": 98.5,
        "branches_pct": 85.4,
    }
    assert payload["jobs"] == {
        "backend": "success",
        "frontend-vitest": "skipped",
        "lint": "success",
    }


def test_cli_handles_missing_and_corrupt_optional_inputs(
    monkeypatch, tmp_path: Path, capsys
) -> None:
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
    out_file = tmp_path / "out" / "ci-post-telemetry.json"
    monkeypatch.setenv("TEST_NEEDS", json.dumps({"lint": {"result": "success"}}))

    rc = ci_telemetry.main(
        [
            "--timing-json",
            str(tmp_path / "missing-timing.json"),
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
    assert rc == 0
    err = capsys.readouterr().err
    assert "ignoring unreadable telemetry JSON" in err
    written = json.loads(out_file.read_text(encoding="utf-8"))
    assert written["timing"] is None
    assert written["coverage"]["backend"] is None
    assert written["coverage"]["frontend"]["lines_pct"] == 98.2
    assert written["jobs"] == {"lint": "success"}

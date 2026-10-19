"""AC-testing.benchmarks.15: the Bench V2 index lists every published run (#2513).

`benchmark.yml` built the index from `docs/benchmarks`. That directory holds the runs that `main` commits
and the current run. Each run replaced `manifest.json` and `index.html` on GitHub Pages with that short list.
On 2026-10-19 Pages held 6 runs and the manifest listed 3. The only full pass of the last month was missing.
The generator now also reads a copy of the published tree, and the workflow fetches that copy first.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from common.testing.benchmarks import generate_benchmark_index as generator

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "benchmark.yml"


def _summary(
    version: str, run_at: str, status: str = "PASS", **extra: Any
) -> dict[str, Any]:
    return {
        "version": version,
        "run_at": run_at,
        "status": status,
        "cases_total": 7,
        "cases_passed": 7 if status == "PASS" else 3,
        "duration_seconds": 12.5,
        "max_equation_delta": "0.00",
        **extra,
    }


def _publish(directory: Path, summary: dict[str, Any]) -> None:
    folder = directory / summary["version"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def _manifest(directory: Path) -> list[dict[str, Any]]:
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))


def test_AC_testing_benchmarks_15_the_index_lists_the_published_runs_and_the_current_run(
    tmp_path: Path,
) -> None:
    current, history = tmp_path / "docs", tmp_path / "published"
    _publish(history, _summary("v0.2.2", "2026-10-15T08:30:00+00:00", "FAIL"))
    _publish(history, _summary("v0.2.3", "2026-10-15T10:19:00+00:00"))
    _publish(current, _summary("v0.2.6", "2026-10-19T09:12:00+00:00"))

    assert (
        generator.main(
            ["--benchmarks-dir", str(current), "--history-dir", str(history)]
        )
        == 0
    )

    manifest = _manifest(current)
    assert [(run["version"], run["status"]) for run in manifest] == [
        ("v0.2.6", "PASS"),
        ("v0.2.3", "PASS"),
        ("v0.2.2", "FAIL"),
    ]
    index = (current / "index.html").read_text(encoding="utf-8")
    assert all(version in index for version in ("v0.2.2", "v0.2.3", "v0.2.6"))


def test_AC_testing_benchmarks_15_a_current_run_replaces_the_published_run_of_the_same_version(
    tmp_path: Path,
) -> None:
    current, history = tmp_path / "docs", tmp_path / "published"
    _publish(history, _summary("v0.2.6", "2026-10-19T07:09:00+00:00", "FAIL"))
    _publish(history, _summary("v0.2.3", "2026-10-15T10:19:00+00:00"))
    _publish(current, _summary("v0.2.6", "2026-10-19T09:12:00+00:00", "PASS"))

    generator.main(["--benchmarks-dir", str(current), "--history-dir", str(history)])

    assert [
        (run["version"], run["status"], run["run_at"]) for run in _manifest(current)
    ] == [
        ("v0.2.6", "PASS", "2026-10-19T09:12:00+00:00"),
        ("v0.2.3", "PASS", "2026-10-15T10:19:00+00:00"),
    ]


def test_AC_testing_benchmarks_15_a_missing_history_directory_leaves_the_current_runs(
    tmp_path: Path,
) -> None:
    current = tmp_path / "docs"
    _publish(current, _summary("v0.2.6", "2026-10-19T09:12:00+00:00"))

    assert (
        generator.main(
            [
                "--benchmarks-dir",
                str(current),
                "--history-dir",
                str(tmp_path / "absent"),
            ]
        )
        == 0
    )

    assert [run["version"] for run in _manifest(current)] == ["v0.2.6"]


def test_AC_testing_benchmarks_15_without_the_history_option_only_the_directory_counts(
    tmp_path: Path,
) -> None:
    current = tmp_path / "docs"
    _publish(current, _summary("v0.2.6", "2026-10-19T09:12:00+00:00"))

    generator.main(["--benchmarks-dir", str(current)])

    assert [run["version"] for run in _manifest(current)] == ["v0.2.6"]


def test_AC_testing_benchmarks_15_a_history_file_that_is_no_summary_is_skipped_with_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    current, history = tmp_path / "docs", tmp_path / "published"
    _publish(history, _summary("v0.2.3", "2026-10-15T10:19:00+00:00"))
    (history / "v0.2.4").mkdir()
    (history / "v0.2.4" / "summary.json").write_text("{not json", encoding="utf-8")
    (history / "v0.2.5").mkdir()
    (history / "v0.2.5" / "summary.json").write_text("[1, 2]", encoding="utf-8")
    _publish(current, _summary("v0.2.6", "2026-10-19T09:12:00+00:00"))

    assert (
        generator.main(
            ["--benchmarks-dir", str(current), "--history-dir", str(history)]
        )
        == 0
    )

    assert [run["version"] for run in _manifest(current)] == ["v0.2.6", "v0.2.3"]
    err = capsys.readouterr().err
    assert "Failed to parse" in err and "v0.2.4" in err
    assert "not a JSON object" in err and "v0.2.5" in err


def _steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["run-benchmark"]["steps"]


def _step_index(steps: list[dict[str, Any]], needle: str) -> int:
    matches = [i for i, step in enumerate(steps) if needle in str(step.get("run", ""))]
    assert len(matches) == 1, (
        f"expected one step that runs {needle!r}, found {len(matches)}"
    )
    return matches[0]


def test_AC_testing_benchmarks_15_the_workflow_fetches_the_published_history_before_it_builds_the_index() -> (
    None
):
    steps = _steps()
    fetch = _step_index(steps, "git fetch --no-tags --depth=1 origin gh-pages")
    build = _step_index(steps, "generate_benchmark_index.py")

    assert fetch < build
    # The index must read the tree that the fetch step extracts.
    assert "git archive --format=tar FETCH_HEAD benchmarks" in steps[fetch]["run"]
    assert '-C "$RUNNER_TEMP/published"' in steps[fetch]["run"]
    assert '--history-dir "$RUNNER_TEMP/published/benchmarks"' in steps[build]["run"]
    # A failed fetch must not skip the index: both steps run after a failed benchmark too.
    assert steps[fetch]["if"] == steps[build]["if"] == "always()"

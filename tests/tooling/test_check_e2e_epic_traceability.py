"""Tests for tools/check_e2e_epic_traceability.py."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from common.ssot import check_e2e_epic_traceability as checker


def _write_epic(repo_root: Path, epic_id: str) -> None:
    project = repo_root / "docs" / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / f"{epic_id}.sample.md").write_text(
        f"# {epic_id}: Sample\n\n- **AC8.13.68**: E2E EPIC traceability.\n",
        encoding="utf-8",
    )


def _write_test(repo_root: Path, rel_path: str, content: str) -> None:
    path = repo_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_AC8_13_68_valid_e2e_epic_traceability_passes(tmp_path: Path) -> None:
    """AC8.13.68: E2E EPIC traceability accepts closed EPIC ownership."""
    _write_epic(tmp_path, "EPIC-001")
    _write_epic(tmp_path, "EPIC-002")
    _write_epic(tmp_path, "EPIC-003")
    _write_test(
        tmp_path,
        "tests/e2e/test_flow.py",
        """
import pytest


@pytest.mark.e2e
async def test_first_flow():
    \"\"\"EPIC-001 / AC8.13.68: first product E2E owner.\"\"\"
    assert True


@pytest.mark.smoke
def test_second_flow():
    \"\"\"EPIC-002 / AC8.13.68: second product E2E owner.\"\"\"
    assert True


def test_unmarked_e2e_root_flow():
    \"\"\"EPIC-003 / AC8.13.68: E2E-root tests count without markers.\"\"\"
    assert True
""",
    )

    result = checker.check_traceability(tmp_path)

    assert result.errors == []
    assert result.covered_epics == ["EPIC-001", "EPIC-002", "EPIC-003"]
    assert [test.name for test in result.tests] == [
        "test_first_flow",
        "test_second_flow",
        "test_unmarked_e2e_root_flow",
    ]


def test_AC8_13_68_missing_function_epic_ref_fails(tmp_path: Path) -> None:
    """AC8.13.68: E2E-root tests without function-level EPIC IDs fail."""
    _write_epic(tmp_path, "EPIC-001")
    _write_test(
        tmp_path,
        "tests/e2e/test_flow.py",
        """
def test_missing_epic_reference():
    \"\"\"AC8.13.68: AC alone is not enough for E2E ownership.\"\"\"
    assert True
""",
    )

    result = checker.check_traceability(tmp_path)

    assert (
        "tests/e2e/test_flow.py:1 test_missing_epic_reference: missing EPIC ID"
        in result.errors
    )
    assert "EPIC-001: no product E2E owner test" in result.errors


def test_AC8_13_68_file_level_epic_ref_does_not_satisfy_test(
    tmp_path: Path,
) -> None:
    """AC8.13.68: File-level EPIC IDs do not satisfy E2E test ownership."""
    _write_epic(tmp_path, "EPIC-001")
    _write_test(
        tmp_path,
        "tests/e2e/test_flow.py",
        """
# EPIC-001 appears here, but not on the test anchor.
def test_file_level_reference_only():
    assert True
""",
    )

    result = checker.check_traceability(tmp_path)

    assert (
        "tests/e2e/test_flow.py:2 test_file_level_reference_only: missing EPIC ID"
        in result.errors
    )
    assert "EPIC-001: no product E2E owner test" in result.errors


def test_AC8_13_68_non_test_functions_are_ignored(tmp_path: Path) -> None:
    """AC8.13.68: E2E discovery ignores helper functions in product E2E roots."""
    _write_epic(tmp_path, "EPIC-001")
    _write_test(
        tmp_path,
        "tests/e2e/test_flow.py",
        """
def helper_flow():
    \"\"\"EPIC-999: helper references do not create E2E ownership.\"\"\"
    return True


def test_owned_flow():
    \"\"\"EPIC-001 / AC8.13.68: product E2E owner.\"\"\"
    assert helper_flow()
""",
    )

    result = checker.check_traceability(tmp_path)

    assert result.errors == []
    assert [test.name for test in result.tests] == ["test_owned_flow"]


def test_AC8_13_68_uncovered_project_epic_fails(tmp_path: Path) -> None:
    """AC8.13.68: Every project EPIC must have product E2E ownership."""
    _write_epic(tmp_path, "EPIC-001")
    _write_epic(tmp_path, "EPIC-002")
    _write_test(
        tmp_path,
        "tests/e2e/test_flow.py",
        """
import pytest


@pytest.mark.e2e
def test_one_epic_only():
    \"\"\"EPIC-001 / AC8.13.68: one owner is present.\"\"\"
    assert True
""",
    )

    result = checker.check_traceability(tmp_path)

    assert "EPIC-002: no product E2E owner test" in result.errors


def test_AC8_13_68_unknown_epic_ref_fails(tmp_path: Path) -> None:
    """AC8.13.68: E2E tests cannot reference non-project EPIC IDs."""
    _write_epic(tmp_path, "EPIC-001")
    _write_test(
        tmp_path,
        "tests/e2e/test_flow.py",
        """
import pytest


@pytest.mark.e2e
def test_unknown_epic_reference():
    \"\"\"EPIC-001 EPIC-999 / AC8.13.68: unknown owner is invalid.\"\"\"
    assert True
""",
    )

    result = checker.check_traceability(tmp_path)

    assert (
        "tests/e2e/test_flow.py:5 test_unknown_epic_reference: unknown EPIC ID EPIC-999"
        in result.errors
    )


def test_AC8_13_68_parse_errors_are_reported(tmp_path: Path) -> None:
    """AC8.13.68: Syntax errors fail closed and appear in the report."""
    _write_epic(tmp_path, "EPIC-001")
    _write_test(
        tmp_path,
        "tests/e2e/test_bad.py",
        """
def test_broken_python(
    assert True
""",
    )

    result = checker.check_traceability(tmp_path)
    report = checker.render_report(result)

    assert len(result.parse_errors) == 1
    assert "tests/e2e/test_bad.py: could not parse Python AST:" in result.errors[0]
    assert "## Errors" in report
    assert "EPIC-001: no product E2E owner test" in report


def test_AC8_13_68_discovery_handles_missing_roots_and_external_paths(
    tmp_path: Path,
) -> None:
    """AC8.13.68: Discovery handles absent SSOT/E2E roots and external files."""
    external = tmp_path.parent / "external_test_file.py"

    assert checker.discover_project_epics(tmp_path) == []
    assert checker.discover_e2e_files(tmp_path, ("missing/e2e",)) == []
    assert checker._rel(external, tmp_path) == external.as_posix()


def test_AC8_13_68_marker_extraction_accepts_calls_and_nested_marks() -> None:
    """AC8.13.68: Marker extraction records stable pytest marker names."""
    module = ast.parse(
        """
import pytest


@pytest.mark.e2e(reason="smoke")
@pytest.mark.smoke.slow
def test_marker_shapes():
    assert True
"""
    )

    assert checker._decorator_markers(module.body[1]) == {"e2e", "smoke"}
    assert checker._decorator_markers(ast.Pass()) == set()


def test_AC8_13_68_main_writes_report_only_output(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """AC8.13.68: CLI report-only mode writes an error report without failing."""
    _write_epic(tmp_path, "EPIC-001")
    _write_test(
        tmp_path,
        "tests/e2e/test_flow.py",
        """
def test_missing_epic_reference():
    assert True
""",
    )
    output = tmp_path / "reports" / "e2e.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_e2e_epic_traceability.py",
            "--repo-root",
            str(tmp_path),
            "--output",
            str(output),
            "--report-only",
        ],
    )

    assert checker.main() == 0
    captured = capsys.readouterr()
    assert f"Wrote E2E EPIC traceability report: {output}" in captured.out
    assert "E2E EPIC TRACEABILITY GATE PASSED" in captured.out
    assert "test_missing_epic_reference: missing EPIC ID" in output.read_text(
        encoding="utf-8"
    )


def test_AC8_13_68_main_fails_when_not_report_only(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """AC8.13.68: CLI exits non-zero when traceability errors are enforced."""
    _write_epic(tmp_path, "EPIC-001")
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_e2e_epic_traceability.py", "--repo-root", str(tmp_path)],
    )

    assert checker.main() == 1
    captured = capsys.readouterr()
    assert "EPIC-001: no product E2E owner test" in captured.out
    assert "E2E EPIC TRACEABILITY GATE FAILED: 1 issue(s) found." in captured.err

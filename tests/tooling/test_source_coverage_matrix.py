"""Source coverage matrix contract tests."""

from pathlib import Path
from textwrap import dedent

import pytest

from common.ssot.check_source_coverage_matrix import SourceCoverageResult
from common.ssot import check_source_coverage_matrix as source_matrix


def _write_repo_fixture(tmp_path: Path) -> Path:
    (tmp_path / "docs" / "project").mkdir(parents=True)
    (tmp_path / "docs" / "project" / "EPIC-003.statement-parsing.md").write_text("# EPIC-003\n", encoding="utf-8")
    anchor = tmp_path / "tests" / "e2e" / "test_source.py"
    anchor.parent.mkdir(parents=True)
    anchor.write_text("def test_source():\n    pass\n", encoding="utf-8")
    return anchor


def _write_matrix(tmp_path: Path, content: str) -> Path:
    matrix = tmp_path / "matrix.yaml"
    matrix.parent.mkdir(parents=True, exist_ok=True)
    matrix.write_text(dedent(content).strip() + "\n", encoding="utf-8")
    return matrix


def _valid_source_yaml(source_id: str = "bank_statement") -> str:
    return f"""  - id: {source_id}
    owner_epics: [EPIC-003]
    supported_formats: [pdf]
    supported_institutions: [DBS]
    proof_levels: [pr_deterministic]
    ingestion_path: /api/statements/upload
    review_requirement: review
    traceability_target: source_to_report
    test_anchors:
      - tests/e2e/test_source.py::test_source"""


def test_AC13_12_1_source_coverage_matrix_covers_vision_source_classes() -> None:
    """AC13.12.1: Source coverage matrix covers every source class named by vision."""
    results = source_matrix.validate_source_coverage(
        source_matrix.REPO_ROOT,
        source_matrix.DEFAULT_MATRIX,
    )
    errors = [error for result in results for error in result.errors]
    assert errors == []

    sources = {
        result.source_id: set(result.proof_levels)
        for result in results
        if not result.source_id.startswith("__")
    }
    assert {
        "bank_statement",
        "brokerage_statement",
        "settlement_note",
        "esop_rsu_plan",
        "property_statement",
        "liability_statement",
        "csv_export",
        "manual_record",
    } == set(sources)
    assert "pr_deterministic" in sources["bank_statement"]
    assert "manual_trusted" in sources["esop_rsu_plan"]


def test_AC13_12_2_source_coverage_matrix_rejects_llm_only_sources(tmp_path: Path) -> None:
    """AC13.12.2: LLM/OCR-only source coverage fails without an explicit exception."""
    _write_repo_fixture(tmp_path)
    matrix = _write_matrix(
        tmp_path,
        """
version: "1.0"
required_source_classes: [bank_statement]
source_classes:
  - id: bank_statement
    owner_epics: [EPIC-003]
    supported_formats: [pdf]
    supported_institutions: [DBS]
    proof_levels: [post_merge_llm_ocr]
    ingestion_path: /api/statements/upload
    review_requirement: review
    traceability_target: source_to_report
    test_anchors:
      - tests/e2e/test_source.py::test_source
""",
    )

    results = source_matrix.validate_source_coverage(tmp_path, matrix)
    errors = [error for result in results for error in result.errors]
    assert "bank_statement: post_merge_llm_ocr cannot be the only proof level" in errors


def test_AC13_12_3_source_coverage_matrix_requires_gap_issue(tmp_path: Path) -> None:
    """AC13.12.3: Gap source coverage must carry an explicit issue reference."""
    _write_repo_fixture(tmp_path)
    matrix = _write_matrix(
        tmp_path,
        """
version: "1.0"
required_source_classes: [settlement_note]
source_classes:
  - id: settlement_note
    owner_epics: [EPIC-003]
    supported_formats: [pdf]
    supported_institutions: [generic_brokerage]
    proof_levels: [gap]
    ingestion_path: /api/statements/upload
    review_requirement: review
    traceability_target: source_to_report
    test_anchors:
      - tests/e2e/test_source.py::test_source
""",
    )

    results = source_matrix.validate_source_coverage(tmp_path, matrix)
    errors = [error for result in results for error in result.errors]
    assert "settlement_note: gap proof level requires gap_issue like #696" in errors


def test_AC13_12_1_source_coverage_matrix_rejects_invalid_shape_and_global_drift(tmp_path: Path) -> None:
    """AC13.12.1: Matrix validation rejects malformed entries and source-class drift."""
    _write_repo_fixture(tmp_path)
    matrix = _write_matrix(
        tmp_path,
        f"""
version: "1.0"
required_source_classes: [bank_statement, csv_export]
source_classes:
{_valid_source_yaml("bank_statement")}
{_valid_source_yaml("bank_statement")}
  - not_a_mapping
{_valid_source_yaml("unexpected_source")}
""",
    )

    results = source_matrix.validate_source_coverage(tmp_path, matrix)
    errors = [error for result in results for error in result.errors]

    assert "source entry must be a mapping" in errors
    assert "missing required source classes: csv_export" in errors
    assert "unknown source classes: unexpected_source" in errors
    assert "duplicate source classes: bank_statement" in errors


def test_AC13_12_1_source_coverage_matrix_rejects_source_field_errors(tmp_path: Path) -> None:
    """AC13.12.1: Source entries must carry valid owners, anchors, proof levels, and IDs."""
    matrix = _write_matrix(
        tmp_path,
        """
version: "1.0"
required_source_classes: [bank_statement]
source_classes:
  - supported_formats: [pdf]
    supported_institutions: [DBS]
    proof_levels: [unknown_level]
    ingestion_path: /api/statements/upload
    review_requirement: review
    traceability_target: source_to_report
    test_anchors:
      - missing.py::test_missing
  - id: bank_statement
    owner_epics: [BAD-1, EPIC-999]
    supported_formats: [pdf]
    supported_institutions: [DBS]
    proof_levels: []
    ingestion_path: /api/statements/upload
    review_requirement: review
    traceability_target: source_to_report
    test_anchors: []
""",
    )

    results = source_matrix.validate_source_coverage(tmp_path, matrix)
    errors = [error for result in results for error in result.errors]

    assert "<missing id>: missing keys: id, owner_epics" in errors
    assert "source class missing id" in errors
    assert ": owner_epics must be a non-empty list" in errors
    assert ": unknown proof levels: unknown_level" in errors
    assert ": test anchor file does not exist: missing.py" in errors
    assert "bank_statement: invalid owner EPIC 'BAD-1'" in errors
    assert "bank_statement: owner EPIC does not exist: EPIC-999" in errors
    assert "bank_statement: proof_levels must be non-empty" in errors
    assert "bank_statement: test_anchors must be a non-empty list" in errors


def test_AC13_12_1_source_coverage_matrix_rejects_non_mapping_and_non_list_sources(tmp_path: Path) -> None:
    """AC13.12.1: Matrix root and source_classes must have the expected YAML shape."""
    scalar_matrix = _write_matrix(tmp_path, "[]")
    with pytest.raises(ValueError, match="must contain a YAML mapping"):
        source_matrix.validate_source_coverage(tmp_path, scalar_matrix)

    non_list_matrix = _write_matrix(
        tmp_path,
        """
version: "1.0"
required_source_classes: [bank_statement]
source_classes: invalid
""",
    )

    results = source_matrix.validate_source_coverage(tmp_path, non_list_matrix)
    assert results == [SourceCoverageResult("__matrix__", errors=["source_classes must be a list"])]


def test_AC13_12_2_source_coverage_matrix_allows_explicit_llm_only_exception(tmp_path: Path) -> None:
    """AC13.12.2: Explicit exceptions can document rare LLM/OCR-only post-merge gates."""
    _write_repo_fixture(tmp_path)
    matrix = _write_matrix(
        tmp_path,
        """
version: "1.0"
required_source_classes: [bank_statement]
source_classes:
  - id: bank_statement
    owner_epics: [EPIC-003]
    supported_formats: [pdf]
    supported_institutions: [DBS]
    proof_levels: [post_merge_llm_ocr]
    requires_pr_deterministic_mirror: false
    ingestion_path: /api/statements/upload
    review_requirement: review
    traceability_target: source_to_report
    test_anchors:
      - tests/e2e/test_source.py::test_source
""",
    )

    results = source_matrix.validate_source_coverage(tmp_path, matrix)
    errors = [error for result in results for error in result.errors]
    assert errors == []


def test_AC13_12_3_source_coverage_matrix_accepts_gap_with_issue(tmp_path: Path) -> None:
    """AC13.12.3: Gap entries are accepted when they point to an explicit issue."""
    _write_repo_fixture(tmp_path)
    matrix = _write_matrix(
        tmp_path,
        """
version: "1.0"
required_source_classes: [settlement_note]
source_classes:
  - id: settlement_note
    owner_epics: [EPIC-003]
    supported_formats: [pdf]
    supported_institutions: [generic_brokerage]
    proof_levels: [gap]
    gap_issue: "#696"
    ingestion_path: /api/statements/upload
    review_requirement: review
    traceability_target: source_to_report
    test_anchors:
      - tests/e2e/test_source.py::test_source
""",
    )

    results = source_matrix.validate_source_coverage(tmp_path, matrix)
    assert [error for result in results for error in result.errors] == []


def test_AC13_12_1_source_coverage_matrix_report_and_cli_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC13.12.1: Source coverage checker reports both passing and failing CLI outcomes."""
    _write_repo_fixture(tmp_path)
    matrix = _write_matrix(
        tmp_path,
        f"""
version: "1.0"
required_source_classes: [bank_statement]
source_classes:
{_valid_source_yaml("bank_statement")}
""",
    )
    failing_matrix = _write_matrix(
        tmp_path / "failing",
        """
version: "1.0"
required_source_classes: [bank_statement]
source_classes: invalid
""",
    )

    assert "No source coverage errors found." in source_matrix.render_report(
        [SourceCoverageResult("bank_statement", ["pr_deterministic"], [])]
    )
    assert "- broken" in source_matrix.render_report([SourceCoverageResult("bank_statement", errors=["broken"])])

    monkeypatch.setattr(
        "sys.argv",
        ["check_source_coverage_matrix.py", "--repo-root", str(tmp_path), "--matrix", str(matrix)],
    )
    assert source_matrix.main() == 0
    assert "Source coverage matrix passed: 1 source class(es) validated." in capsys.readouterr().out

    monkeypatch.setattr(
        "sys.argv",
        ["check_source_coverage_matrix.py", "--repo-root", str(tmp_path), "--matrix", str(failing_matrix)],
    )
    assert source_matrix.main() == 1
    captured = capsys.readouterr()
    assert "source_classes must be a list" in captured.out
    assert "::error title=Source coverage matrix::source_classes must be a list" in captured.err

"""Tests for scripts/check_critical_proof_matrix.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import check_critical_proof_matrix as matrix  # noqa: E402


def _write_registry(repo_root: Path) -> None:
    docs = repo_root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "ac_registry.yaml").write_text(
        """
version: '1.0'
groups:
  AC8:
    AC8.13:
      - id: AC8.13.1
        epic: 8
        epic_name: testing-strategy
        description: core upload proof
        mandatory: true
      - id: AC8.13.2
        epic: 8
        epic_name: testing-strategy
        description: core parsed proof
        mandatory: true
      - id: AC8.13.40
        epic: 8
        epic_name: testing-strategy
        description: critical proof matrix validates core paths
        mandatory: true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (docs / "infra_registry.yaml").write_text(
        "version: '1.0'\ngroups: {}\n",
        encoding="utf-8",
    )


def _write_matrix(repo_root: Path, content: str) -> Path:
    matrix_path = repo_root / "docs" / "ssot" / "critical-proof-matrix.yaml"
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    matrix_path.write_text(content.strip() + "\n", encoding="utf-8")
    return matrix_path


def test_valid_behavioral_static_and_manual_entries_pass(tmp_path: Path) -> None:
    """AC8.13.40: Critical proof matrix accepts explicit proof classes."""
    _write_registry(tmp_path)
    test_dir = tmp_path / "tests" / "e2e"
    test_dir.mkdir(parents=True)
    (test_dir / "test_core.py").write_text(
        """
import pytest

@pytest.mark.e2e
@pytest.mark.critical
async def test_core_flow():
    \"\"\"AC8.13.1 AC8.13.2: core path proof.\"\"\"
    assert True
""".strip()
        + "\n",
        encoding="utf-8",
    )
    scripts_dir = tmp_path / "scripts" / "tests"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "test_contract.py").write_text(
        """
def test_contract_shape():
    \"\"\"AC8.13.40: static checker contract.\"\"\"
    assert True
""".strip()
        + "\n",
        encoding="utf-8",
    )
    matrix_path = _write_matrix(
        tmp_path,
        """
version: "1.0"
proofs:
  - id: core-flow
    scope: behavioral
    ci_tier: post_merge_environment
    file: tests/e2e/test_core.py
    test: test_core_flow
    required_markers: [e2e, critical]
    ac_ids: [AC8.13.1, AC8.13.2]
  - id: static-contract
    scope: static_contract
    ci_tier: pr_ci
    file: scripts/tests/test_contract.py
    test: test_contract_shape
    ac_ids: [AC8.13.40]
  - id: manual-provider-gate
    scope: manual_gate
    ci_tier: manual
    evidence: "Provider dashboard reviewed by release owner."
    ac_ids: [AC8.13.2]
""",
    )

    results = matrix.validate_matrix(tmp_path, matrix_path)
    assert [result.status for result in results] == [
        "behavioral",
        "static_contract",
        "manual",
    ]
    assert not [error for result in results for error in result.errors]

    report = matrix.render_report(results)
    assert "Behavioral proof | 1" in report
    assert "Static/doc check | 1" in report
    assert "Manual-only gate | 1" in report


def test_file_level_ac_reference_does_not_satisfy_core_proof(tmp_path: Path) -> None:
    """AC8.13.40: File/body-only AC strings are reference-only for core paths."""
    _write_registry(tmp_path)
    test_dir = tmp_path / "tests" / "e2e"
    test_dir.mkdir(parents=True)
    (test_dir / "test_core.py").write_text(
        """
# AC8.13.1 appears here, but not in the test anchor.
import pytest

@pytest.mark.e2e
@pytest.mark.critical
async def test_core_flow():
    assert True  # AC8.13.2
""".strip()
        + "\n",
        encoding="utf-8",
    )
    matrix_path = _write_matrix(
        tmp_path,
        """
version: "1.0"
proofs:
  - id: core-flow
    scope: behavioral
    ci_tier: post_merge_environment
    file: tests/e2e/test_core.py
    test: test_core_flow
    required_markers: [e2e, critical]
    ac_ids: [AC8.13.1, AC8.13.2]
""",
    )

    [result] = matrix.validate_matrix(tmp_path, matrix_path)
    assert result.status == "fail"
    assert any("only a file/body reference" in error for error in result.errors)


def test_broad_contract_file_cannot_satisfy_behavioral_proof(tmp_path: Path) -> None:
    """AC8.13.40: Broad contract tests cannot close core behavioral proof."""
    _write_registry(tmp_path)
    test_dir = tmp_path / "scripts" / "tests"
    test_dir.mkdir(parents=True)
    (test_dir / "test_issue_459_infra_contracts.py").write_text(
        """
def test_many_contracts():
    \"\"\"AC8.13.1: broad contract bucket.\"\"\"
    assert True
""".strip()
        + "\n",
        encoding="utf-8",
    )
    matrix_path = _write_matrix(
        tmp_path,
        """
version: "1.0"
proofs:
  - id: fake-core-flow
    scope: behavioral
    ci_tier: post_merge_environment
    file: scripts/tests/test_issue_459_infra_contracts.py
    test: test_many_contracts
    ac_ids: [AC8.13.1]
""",
    )

    [result] = matrix.validate_matrix(tmp_path, matrix_path)
    assert result.status == "fail"
    assert any("broad contract tests cannot satisfy critical proof" in error for error in result.errors)
    assert any("behavioral proof must live under product test roots" in error for error in result.errors)


def test_unknown_ac_missing_file_and_missing_marker_fail(tmp_path: Path) -> None:
    """AC8.13.40: Matrix drift reports missing ACs, files, and markers."""
    _write_registry(tmp_path)
    test_dir = tmp_path / "tests" / "e2e"
    test_dir.mkdir(parents=True)
    (test_dir / "test_core.py").write_text(
        """
import pytest

@pytest.mark.e2e
async def test_core_flow():
    \"\"\"AC8.13.1: core path proof.\"\"\"
    assert True
""".strip()
        + "\n",
        encoding="utf-8",
    )
    matrix_path = _write_matrix(
        tmp_path,
        """
version: "1.0"
proofs:
  - id: missing-marker-and-ac
    scope: behavioral
    ci_tier: post_merge_environment
    file: tests/e2e/test_core.py
    test: test_core_flow
    required_markers: [e2e, critical]
    ac_ids: [AC8.13.1, AC8.13.99]
  - id: missing-file
    scope: behavioral
    ci_tier: post_merge_environment
    file: tests/e2e/test_missing.py
    test: test_missing
    ac_ids: [AC8.13.1]
""",
    )

    results = matrix.validate_matrix(tmp_path, matrix_path)
    errors = [error for result in results for error in result.errors]
    assert any("unknown AC id AC8.13.99" in error for error in errors)
    assert any("missing pytest markers" in error for error in errors)
    assert any("file does not exist" in error for error in errors)


def test_typescript_anchor_and_missing_test_anchor_are_validated(tmp_path: Path) -> None:
    """AC8.13.40: Frontend test titles can carry stable critical AC proof."""
    _write_registry(tmp_path)
    frontend_dir = tmp_path / "apps" / "frontend" / "src"
    frontend_dir.mkdir(parents=True)
    (frontend_dir / "upload.test.tsx").write_text(
        """
import { test } from "vitest";

test("AC8.13.1 upload journey renders", () => {
  expect(true).toBe(true);
});
""".strip()
        + "\n",
        encoding="utf-8",
    )
    matrix_path = _write_matrix(
        tmp_path,
        """
version: "1.0"
proofs:
  - id: frontend-upload
    scope: behavioral
    ci_tier: pr_ci
    file: apps/frontend/src/upload.test.tsx
    test: AC8.13.1 upload journey renders
    ac_ids: [AC8.13.1]
  - id: missing-anchor
    scope: static_contract
    ci_tier: pr_ci
    file: apps/frontend/src/upload.test.tsx
    test: AC8.13.1 missing title
    ac_ids: [AC8.13.1]
""",
    )

    valid, invalid = matrix.validate_matrix(tmp_path, matrix_path)
    assert valid.status == "behavioral"
    assert not valid.errors
    assert invalid.status == "fail"
    assert invalid.errors == ["missing-anchor: test anchor not found: AC8.13.1 missing title"]


def test_shape_errors_are_reported_before_file_validation(tmp_path: Path) -> None:
    """AC8.13.40: Malformed proof rows fail with actionable messages."""
    _write_registry(tmp_path)
    matrix_path = _write_matrix(
        tmp_path,
        """
version: "1.0"
proofs:
  - id: bad-shape
    scope: behaviorish
    ci_tier: someday
    ac_ids: []
  - id: manual-without-evidence
    scope: manual_gate
    ci_tier: manual
    ac_ids: [AC8.13.1]
  - scope: behavioral
    ci_tier: pr_ci
    ac_ids: [AC8.13.1]
""",
    )

    results = matrix.validate_matrix(tmp_path, matrix_path)
    errors = [error for result in results for error in result.errors]
    assert "bad-shape: invalid scope 'behaviorish'" in errors
    assert "bad-shape: invalid ci_tier 'someday'" in errors
    assert "bad-shape: ac_ids must be a non-empty list" in errors
    assert "bad-shape: file is required for behaviorish" in errors
    assert "bad-shape: test is required for behaviorish" in errors
    assert "manual-without-evidence: evidence is required for manual_gate" in errors
    assert "proof[2] missing required keys: id" in errors


def test_invalid_matrix_yaml_shapes_raise_value_error(tmp_path: Path) -> None:
    """AC8.13.40: Matrix files must stay as explicit proof mappings."""
    scalar_matrix = tmp_path / "scalar.yaml"
    scalar_matrix.write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain a YAML mapping"):
        matrix._load_matrix(scalar_matrix)

    _write_registry(tmp_path)
    empty_matrix = _write_matrix(
        tmp_path,
        """
version: "1.0"
proofs: []
""",
    )
    with pytest.raises(ValueError, match="must define a non-empty proofs list"):
        matrix.validate_matrix(tmp_path, empty_matrix)


def test_stub_path_unknown_suffix_and_external_relative_helpers(tmp_path: Path) -> None:
    """AC8.13.40: Critical proof cannot be delegated to stubs or unknown anchors."""
    _write_registry(tmp_path)
    stub_dir = tmp_path / "tests" / "e2e" / "_ac_stubs"
    stub_dir.mkdir(parents=True)
    (stub_dir / "proof.txt").write_text("AC8.13.1\n", encoding="utf-8")
    matrix_path = _write_matrix(
        tmp_path,
        """
version: "1.0"
proofs:
  - id: stub-proof
    scope: behavioral
    ci_tier: pr_ci
    file: tests/e2e/_ac_stubs/proof.txt
    test: AC8.13.1 proof
    ac_ids: [AC8.13.1]
""",
    )

    [result] = matrix.validate_matrix(tmp_path, matrix_path)
    assert result.status == "fail"
    assert "stub-proof: critical proof cannot point at _ac_stubs" in result.errors
    assert "stub-proof: test anchor not found: AC8.13.1 proof" in result.errors
    assert matrix._rel(Path("/outside/file.py"), tmp_path) == "/outside/file.py"


def test_main_writes_success_report_and_prints_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.40: CLI behavior is covered for success and failure paths."""
    _write_registry(tmp_path)
    test_dir = tmp_path / "tests" / "e2e"
    test_dir.mkdir(parents=True)
    (test_dir / "test_core.py").write_text(
        """
def test_core_flow():
    \"\"\"AC8.13.1: core path proof.\"\"\"
    assert True
""".strip()
        + "\n",
        encoding="utf-8",
    )
    success_matrix = _write_matrix(
        tmp_path,
        """
version: "1.0"
proofs:
  - id: core-flow
    scope: behavioral
    ci_tier: pr_ci
    file: tests/e2e/test_core.py
    test: test_core_flow
    ac_ids: [AC8.13.1]
""",
    )
    output_path = tmp_path / "reports" / "critical.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_critical_proof_matrix.py",
            "--repo-root",
            str(tmp_path),
            "--matrix",
            str(success_matrix),
            "--output",
            str(output_path),
        ],
    )

    assert matrix.main() == 0
    stdout = capsys.readouterr().out
    assert "Wrote critical proof matrix report" in stdout
    assert "Critical proof matrix passed: 1 proof path(s) validated." in stdout
    assert "| `core-flow` | behavioral | pr_ci |" in output_path.read_text(encoding="utf-8")

    failure_matrix = _write_matrix(
        tmp_path,
        """
version: "1.0"
proofs:
  - id: missing-anchor
    scope: behavioral
    ci_tier: pr_ci
    file: tests/e2e/test_core.py
    test: test_missing_flow
    ac_ids: [AC8.13.1]
""",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_critical_proof_matrix.py",
            "--repo-root",
            str(tmp_path),
            "--matrix",
            str(failure_matrix),
        ],
    )

    assert matrix.main() == 1
    captured = capsys.readouterr()
    assert "# Critical Proof Matrix Report" in captured.out
    assert "Missing or reference-only | 1" in captured.out
    assert "::error title=Critical proof matrix::missing-anchor" in captured.err

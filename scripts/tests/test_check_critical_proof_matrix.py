"""Tests for scripts/check_critical_proof_matrix.py."""

from __future__ import annotations

import sys
from pathlib import Path

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

"""Live governance proof for extraction issue #1995."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from common.extraction.contract import CONTRACT
from common.extraction.extension.governance_detector import (
    GOVERNANCE_SOURCE_PATHS,
    detect_governance,
)
from common.meta.base.governance_control import DetectorObservation
from common.meta.data.governance_control import governance_control_index
from common.testing.ac_proof import ac_proof
from common.testing.package_governance_observations import (
    discover_package_detector_payloads,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

COUNTERFACTUALS = (
    (
        "per-currency-approval",
        "apps/backend/src/extraction/extension/statement_validation.py",
        '"balance_valid": all(row["closing_match"] for row in per_currency)',
        '"balance_valid": primary["closing_match"]',
    ),
    (
        "one-source-identity",
        "apps/backend/src/extraction/orm/layer1.py",
        '"uq_uploaded_documents_user_file_hash"',
        '"uq_uploaded_documents_user_file_hash_disabled"',
    ),
    (
        "session-recovery",
        "apps/backend/src/extraction/extension/source_lifecycle.py",
        "async with db.begin_nested():",
        "if True:",
    ),
    (
        "append-only-retirement",
        "apps/backend/src/extraction/extension/source_lifecycle.py",
        "statement.status = BankStatementStatus.RETIRED",
        "statement.status = BankStatementStatus.PARSED",
    ),
    (
        "storage-db-consistency",
        "apps/backend/src/routers/statements.py",
        "    try:\n        await retire_statement(",
        "    try:\n        StorageService().delete_object(statement_id)\n        await retire_statement(",
    ),
    (
        "failure-convergence",
        "apps/backend/src/routers/statements.py",
        "reset_for_retry=True",
        "reset_for_retry=False",
    ),
    (
        "typed-command-boundary",
        "apps/backend/src/extraction/extension/source_lifecycle.py",
        "if not isinstance(self.user_id, UUID):",
        "if False:",
    ),
    (
        "purge-boundary",
        "apps/backend/src/routers/statements.py",
        "        await retire_statement(\n            db,\n            RetireStatementCommand(statement_id=statement_id, user_id=user_id),\n        )",
        "        await db.delete(statement)",
    ),
    (
        "exact-governance-detail",
        "common/extraction/contract.py",
        "finance_report/issues/1995",
        "finance_report/issues/1970",
    ),
    (
        "counterfactual-lock",
        "apps/backend/tests/extraction/test_source_lifecycle.py",
        'orphan["declared_balance"] is False',
        'orphan["declared_balance"] is True',
    ),
)


def _copy_governance_sources(destination: Path) -> None:
    for relative in GOVERNANCE_SOURCE_PATHS:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)


@pytest.mark.parametrize("failure", ["missing", "syntax"])
def test_detector_reports_unreadable_structure_as_a_finding(tmp_path: Path, failure: str) -> None:
    """AC-extraction.source-lifecycle.9: broken input is never green or lost."""
    _copy_governance_sources(tmp_path)
    path = tmp_path / "apps/backend/src/extraction/extension/source_lifecycle.py"
    if failure == "missing":
        path.unlink()
    else:
        path.write_text("def broken(:\n", encoding="utf-8")
    observations = {item["guarantee_id"]: item for item in detect_governance(repo_root=tmp_path)}
    assert len(observations) == 10
    broken = observations["extraction/session-recovery"]
    assert broken["current"] > broken["target"]
    assert broken["findings"]
    assert observations["extraction/per-currency-approval"]["current"] == 0


def test_detector_ignores_format_only_changes(tmp_path: Path) -> None:
    """AC-extraction.source-lifecycle.9: formatting is not a schema gap."""
    _copy_governance_sources(tmp_path)
    path = tmp_path / "apps/backend/src/extraction/extension/source_lifecycle.py"
    original = path.read_text(encoding="utf-8")
    reformatted = original.replace(
        "statement.status = BankStatementStatus.RETIRED\n    if statement.uploaded_document_id is not None:",
        "statement.status = BankStatementStatus.RETIRED\n\n    if statement.uploaded_document_id is not None:",
    )
    assert reformatted != original
    path.write_text(reformatted, encoding="utf-8")
    assert all(item["current"] == item["target"] for item in detect_governance(repo_root=tmp_path))


@ac_proof(
    "source-lifecycle-governance-detail",
    ac_ids=["AC-extraction.source-lifecycle.9"],
    ci_tier="pr_ci",
    scenario_id="AC-extraction.source-lifecycle.9",
    oracle_kind="live_detector_counterfactual",
    governance_strength="exact",
)
def test_AC_extraction_source_lifecycle_9_governance_detail_is_exact(tmp_path: Path) -> None:
    """AC-extraction.source-lifecycle.9: live facts fail closed."""
    target_sha = "1" * 40
    payloads = discover_package_detector_payloads(
        contracts=[CONTRACT],
        repo_root=REPO_ROOT,
        target_sha=target_sha,
    )
    payload = next(item for item in payloads if item["source"] == "package-detector")
    observations = payload["detectors"]
    assert payload["target_sha"] == target_sha
    assert len(observations) == 10
    assert {item["guarantee_id"] for item in observations} == {
        f"extraction/{guarantee.id}" for initiative in CONTRACT.governance for guarantee in initiative.guarantees
    }
    assert all(item["current"] == item["target"] == 0 for item in observations)

    report = governance_control_index(
        [CONTRACT],
        target_sha=target_sha,
        detector_observations=[DetectorObservation.model_validate(item) for item in observations],
        proof_observations=[],
        enforcement_observations=[],
        issue_observations=[],
        observed_at=datetime(2026, 7, 20, tzinfo=UTC),
    )
    for observation in observations:
        row = report["guarantees"][observation["guarantee_id"]]
        assert row["current"] == row["target"] == 0
        assert row["state"] != "enforced"

    _copy_governance_sources(tmp_path)
    for guarantee_id, relative, old, new in COUNTERFACTUALS:
        path = tmp_path / relative
        original = path.read_text(encoding="utf-8")
        assert old in original, f"Expected {old!r} in {relative}"
        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        mutated = {item["guarantee_id"]: item for item in detect_governance(repo_root=tmp_path)}
        finding = mutated[f"extraction/{guarantee_id}"]
        assert finding["current"] > 0, f"Mutation {guarantee_id} failed to trigger detector finding"
        assert finding["findings"]
        path.write_text(original, encoding="utf-8")

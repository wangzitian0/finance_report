"""Live governance proof for reporting issue #1996."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from common.meta.base.governance_control import DetectorObservation
from common.meta.data.governance_control import governance_control_index
from common.reporting.contract import CONTRACT
from common.reporting.extension.governance_detector import (
    GOVERNANCE_SOURCE_PATHS,
    detect_governance,
)
from common.testing.ac_proof import ac_proof
from common.testing.package_governance_observations import (
    discover_package_detector_payloads,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

COUNTERFACTUALS = (
    (
        "cash-touch-only",
        "apps/backend/src/reporting/extension/cash_flow.py",
        "if not cash_lines:",
        "if False:",
    ),
    (
        "event-classification",
        "apps/backend/src/reporting/extension/cash_flow.py",
        "counterpart_types = {account.type for _line, account in self.counterpart_lines}",
        "counterpart_types = set()",
    ),
    (
        "transfer-neutrality",
        "apps/backend/src/reporting/extension/cash_flow.py",
        "account.is_system and account.code == _PROCESSING_ACCOUNT.code and account.type == AccountType.ASSET",
        "False",
    ),
    (
        "cash-bridge",
        "apps/backend/src/reporting/extension/cash_flow.py",
        "bridge_total = _quantize_money(classified_activity + unclassified_cash + fx_effect + opening_stock_adjustment)",
        "bridge_total = classified_activity",
    ),
    (
        "dual-tenant-isolation",
        "apps/backend/src/reporting/extension/cash_flow.py",
        "where(foreign_account.user_id != user_id)",
        "where(foreign_account.user_id == user_id)",
    ),
    (
        "one-projection-owner",
        "apps/backend/src/reporting/__init__.py",
        '"generate_cash_flow": "src.reporting.extension.cash_flow",',
        '"generate_cash_flow_v2": "src.reporting.extension.cash_flow",',
    ),
    (
        "consumer-proof-state",
        "apps/backend/src/reporting/extension/cash_flow.py",
        '"proof_state": "proven" if not proof_reasons else "unproven"',
        '"proof_state": "proven"',
    ),
    (
        "event-lineage",
        "apps/backend/src/reporting/extension/cash_flow.py",
        '"decision_authority_state": event.entry.decision_authority_state.value,',
        '"decision_authority_state": "fixed",',
    ),
    (
        "exact-governance-detail",
        "common/reporting/contract.py",
        'issue="https://github.com/wangzitian0/finance_report/issues/1996"',
        'issue="https://github.com/wangzitian0/finance_report/issues/1971"',
    ),
    (
        "counterfactual-lock",
        "apps/backend/tests/reporting/test_cash_event_projection.py",
        'voided.void_reason = "Counterfactual fixture"',
        'voided.void_reason = "Disabled fixture"',
    ),
)


def _copy_governance_sources(destination: Path) -> None:
    for relative in GOVERNANCE_SOURCE_PATHS:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)


@pytest.mark.parametrize("failure", ["missing", "syntax"])
def test_detector_reports_unreadable_structure_as_a_finding(tmp_path: Path, failure: str) -> None:
    """AC-reporting.cash-events.9: broken input is never green or lost."""
    _copy_governance_sources(tmp_path)
    path = tmp_path / "apps/backend/src/reporting/extension/cash_flow.py"
    if failure == "missing":
        path.unlink()
    else:
        path.write_text("def broken(:\n", encoding="utf-8")
    observations = {item["guarantee_id"]: item for item in detect_governance(repo_root=tmp_path)}
    assert len(observations) == 10
    broken = observations["reporting/cash-touch-only"]
    assert broken["current"] > broken["target"]
    assert broken["findings"]
    assert observations["reporting/one-projection-owner"]["current"] == 0


def test_detector_ignores_format_only_changes(tmp_path: Path) -> None:
    """AC-reporting.cash-events.9: formatting is not a schema gap."""
    _copy_governance_sources(tmp_path)
    path = tmp_path / "apps/backend/src/reporting/extension/cash_flow.py"
    original = path.read_text(encoding="utf-8")
    reformatted = original.replace(
        "if not cash_lines:\n            continue",
        "if not cash_lines:\n\n            continue",
    )
    assert reformatted != original
    path.write_text(reformatted, encoding="utf-8")
    assert all(item["current"] == item["target"] for item in detect_governance(repo_root=tmp_path))


@ac_proof(
    "governance-detail-lossless-projection",
    ac_ids=["AC-reporting.cash-events.9"],
    ci_tier="pr_ci",
    scenario_id="AC-reporting.cash-events.9",
    oracle_kind="live_detector_projection",
    governance_strength="exact",
)
def test_AC_reporting_cash_events_9_governance_detail_is_package_owned_and_enforced() -> None:
    """AC-reporting.cash-events.9: live facts fail closed."""
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
        f"reporting/{guarantee.id}" for initiative in CONTRACT.governance for guarantee in initiative.guarantees
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


@ac_proof(
    "cash-event-counterfactual-matrix",
    ac_ids=["AC-reporting.cash-events.10"],
    ci_tier="pr_ci",
    scenario_id="AC-reporting.cash-events.10",
    oracle_kind="live_detector_counterfactual",
    governance_strength="exact",
)
def test_AC_reporting_cash_events_10_counterfactual_matrix_is_locked(tmp_path: Path) -> None:
    """AC-reporting.cash-events.10: all 10 cash-event guarantees fail closed under mutation."""
    _copy_governance_sources(tmp_path)
    for guarantee_id, relative, old, new in COUNTERFACTUALS:
        path = tmp_path / relative
        original = path.read_text(encoding="utf-8")
        assert old in original, f"Expected {old!r} in {relative}"
        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        mutated = {item["guarantee_id"]: item for item in detect_governance(repo_root=tmp_path)}
        finding = mutated[f"reporting/{guarantee_id}"]
        assert finding["current"] > 0, f"Mutation {guarantee_id} failed to trigger detector finding"
        assert finding["findings"]
        path.write_text(original, encoding="utf-8")

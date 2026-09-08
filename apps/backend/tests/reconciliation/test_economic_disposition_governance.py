"""Live governance proof for reconciliation issue #1994."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from common.meta.base.governance_control import DetectorObservation
from common.meta.data.governance_control import governance_control_index
from common.reconciliation.contract import CONTRACT
from common.reconciliation.extension.governance_detector import (
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
        "normal-candidate-first",
        "apps/backend/src/reconciliation/extension/matching.py",
        "await run_normal_matching_phase(",
        "await removed_normal_matching_phase(",
    ),
    (
        "one-active-head",
        "apps/backend/src/reconciliation/orm/reconciliation.py",
        '"atomic_txn_id",\n            unique=True',
        '"atomic_txn_id",\n            unique=False',
    ),
    (
        "worker-convergence",
        "apps/backend/src/reconciliation/extension/repository.py",
        ".with_for_update()",
        "",
    ),
    (
        "persistent-transfer-pair",
        "apps/backend/src/reconciliation/orm/reconciliation.py",
        "nullable=False,\n        unique=True",
        "nullable=False,\n        unique=False",
    ),
    (
        "currency-explicit",
        "apps/backend/src/reconciliation/extension/entry_reads.py",
        "def entry_total_amount(entry: JournalEntry, *, currency: str)",
        'def entry_total_amount(entry: JournalEntry, *, currency: str = "SGD")',
    ),
    (
        "idempotent-command",
        "apps/backend/src/reconciliation/extension/transfer_pairs.py",
        "async with db.begin_nested():",
        "if True:",
    ),
    (
        "typed-ledger-boundary",
        "apps/backend/src/reconciliation/extension/phases/transfer_detection.py",
        "await create_transfer_out_entry(",
        "await alternate_transfer_out_entry(",
    ),
    (
        "exact-governance-detail",
        "common/reconciliation/contract.py",
        "finance_report/issues/1994",
        "finance_report/issues/1969",
    ),
)


def _copy_governance_sources(destination: Path) -> None:
    for relative in GOVERNANCE_SOURCE_PATHS:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)


@ac_proof(
    "economic-disposition-governance-detail",
    ac_ids=["AC-reconciliation.economic-disposition.8"],
    ci_tier="pr_ci",
    scenario_id="AC-reconciliation.economic-disposition.8",
    oracle_kind="live_detector_counterfactual",
    governance_strength="exact",
)
def test_AC_reconciliation_economic_disposition_8_governance_detail_is_exact(tmp_path: Path) -> None:
    """AC-reconciliation.economic-disposition.8: live facts fail closed."""
    target_sha = "1" * 40
    payloads = discover_package_detector_payloads(
        contracts=[CONTRACT],
        repo_root=REPO_ROOT,
        target_sha=target_sha,
    )
    payload = next(item for item in payloads if item["source"] == "package-detector")
    observations = payload["detectors"]
    assert payload["target_sha"] == target_sha
    assert len(observations) == 8
    assert {item["guarantee_id"] for item in observations} == {
        f"reconciliation/{guarantee.id}" for initiative in CONTRACT.governance for guarantee in initiative.guarantees
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
        assert old in original
        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        mutated = {item["guarantee_id"]: item for item in detect_governance(repo_root=tmp_path)}
        finding = mutated[f"reconciliation/{guarantee_id}"]
        assert finding["current"] > 0
        assert finding["findings"]
        path.write_text(original, encoding="utf-8")

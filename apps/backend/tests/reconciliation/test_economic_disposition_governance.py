"""Control-plane projection proof for reconciliation issue #1969."""

from __future__ import annotations

from datetime import UTC, datetime

from common.meta.base.governance_control import (
    DetectorObservation,
    EnforcementObservation,
    IssueObservation,
    ProofObservation,
)
from common.meta.data.governance_control import governance_control_index
from common.meta.extension.governance_control_report import render_governance_markdown
from common.reconciliation.contract import CONTRACT


def test_AC_reconciliation_economic_disposition_8_governance_detail_is_exact() -> None:
    """AC-reconciliation.economic-disposition.8: detail is joined, exact, and enforced."""
    target_sha = "1" * 40
    observed_at = datetime(2026, 7, 20, tzinfo=UTC)
    initiative = next(item for item in CONTRACT.governance if item.id == "economic-disposition-atomicity")
    affected_ids = {ac_id for guarantee in initiative.guarantees for ac_id in guarantee.affected_acs}
    completed_contract = CONTRACT.model_copy(
        update={
            "roadmap": [
                ac.model_copy(update={"status": "done"}) if ac.id in affected_ids else ac for ac in CONTRACT.roadmap
            ]
        }
    )
    detectors = [
        DetectorObservation(
            guarantee_id=f"reconciliation/{guarantee.id}",
            current=0,
            target=0,
            findings=[],
        )
        for guarantee in initiative.guarantees
    ]
    proofs = [
        ProofObservation(
            guarantee_id=f"reconciliation/{guarantee.id}",
            proof_id=guarantee.proof,
            result="passed",
            strength=guarantee.required_proof_strength,
            target_sha=target_sha,
            occurred_at=observed_at,
            evidence_url="https://github.com/wangzitian0/finance_report/actions/runs/1969",
            gate_id=guarantee.enforcing_gate,
        )
        for guarantee in initiative.guarantees
    ]
    enforcement = [
        EnforcementObservation(
            gate_id=gate_id,
            declared_blocking=True,
            workflow_required=True,
            live_required=True,
            required_context="finish",
            observed_at=observed_at,
        )
        for gate_id in sorted({item.enforcing_gate for item in initiative.guarantees})
    ]
    report = governance_control_index(
        [completed_contract],
        target_sha=target_sha,
        detector_observations=detectors,
        proof_observations=proofs,
        enforcement_observations=enforcement,
        issue_observations=[
            IssueObservation(
                issue=initiative.issue,
                state="OPEN",
                observed_at=observed_at,
            )
        ],
        observed_at=observed_at,
    )

    initiative_row = report["initiatives"]["reconciliation/economic-disposition-atomicity"]
    assert initiative_row["state"] == "enforced"
    assert initiative_row["open_guarantees"] == 0
    assert initiative_row["blocked_guarantees"] == 0
    for guarantee in initiative.guarantees:
        row = report["guarantees"][f"reconciliation/{guarantee.id}"]
        assert row["state"] == "enforced"
        assert row["proof"]["target_sha"] == target_sha
        assert row["proof"]["strength"] == guarantee.required_proof_strength
        assert row["enforcement"]["live_required"] is True
    markdown = render_governance_markdown(report)
    assert "Economic disposition atomicity and persistent transfer state" in markdown
    assert "worker-convergence" in markdown

"""Pure joined projection for package governance declarations and observations."""

from __future__ import annotations

from datetime import datetime

from common.meta.base.governance_control import (
    DetectorObservation,
    EnforcementObservation,
    IssueObservation,
    ProofObservation,
)
from common.meta.base.package_contract import PackageContract


def _unique(items: list[object], attribute: str, label: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for item in items:
        key = str(getattr(item, attribute))
        if key in result:
            raise ValueError(f"duplicate {label} observation for {key!r}")
        result[key] = item
    return result


def _finding(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def governance_control_index(
    contracts: list[PackageContract],
    *,
    target_sha: str,
    detector_observations: list[DetectorObservation],
    proof_observations: list[ProofObservation],
    enforcement_observations: list[EnforcementObservation],
    issue_observations: list[IssueObservation],
    observed_at: datetime,
) -> dict[str, object]:
    """Join declarations to exact observations; every absent edge stays visible."""

    detectors = _unique(detector_observations, "guarantee_id", "detector")
    proofs = _unique(proof_observations, "guarantee_id", "proof")
    gates = _unique(enforcement_observations, "gate_id", "enforcement")
    issues = _unique(issue_observations, "issue", "issue")
    roadmap = {ac.id: ac for contract in contracts for ac in contract.roadmap}

    initiative_rows: dict[str, dict] = {}
    guarantee_rows: dict[str, dict] = {}
    for contract in contracts:
        for initiative in contract.governance:
            initiative_id = f"{contract.name}/{initiative.id}"
            initiative_findings: list[dict[str, str]] = []
            guarantee_keys: list[str] = []

            issue = issues.get(initiative.issue)
            if issue is None:
                initiative_findings.append(
                    _finding("missing-issue-observation", "No current GitHub issue observation was supplied.")
                )
            elif issue.state == "CLOSED":
                initiative_findings.append(
                    _finding("closed-issue-has-active-initiative", "The issue is closed while its package initiative remains declared.")
                )

            for guarantee in initiative.guarantees:
                guarantee_id = f"{contract.name}/{guarantee.id}"
                guarantee_keys.append(guarantee_id)
                findings: list[dict[str, str]] = []
                detector = detectors.get(guarantee_id)
                proof = proofs.get(guarantee_id)
                gate = gates.get(guarantee.enforcing_gate)

                open_acs = [
                    ac_id for ac_id in guarantee.affected_acs if roadmap[ac_id].status == "open"
                ]
                if open_acs:
                    findings.append(_finding("open-acceptance-criteria", f"Open ACs: {open_acs}"))
                if detector is None:
                    findings.append(_finding("missing-detector-observation", "Detector did not produce a result."))
                else:
                    findings.extend(_finding("detector-finding", item) for item in detector.findings)
                    if detector.current != detector.target:
                        findings.append(_finding("target-not-met", "Detector current value does not equal target."))

                if proof is None:
                    findings.append(_finding("missing-proof-observation", "No executed proof was supplied."))
                else:
                    if proof.proof_id != guarantee.proof:
                        findings.append(_finding("wrong-proof", "Observed proof does not match the declaration."))
                    if proof.result != "passed":
                        findings.append(_finding("proof-not-passed", f"Proof result is {proof.result}."))
                    if proof.target_sha != target_sha:
                        findings.append(_finding("stale-proof", "Proof did not execute against the target SHA."))
                    if proof.strength != guarantee.required_proof_strength:
                        findings.append(_finding("proof-strength-mismatch", "Observed proof strength cannot establish this guarantee."))
                    if proof.gate_id != guarantee.enforcing_gate:
                        findings.append(_finding("proof-not-on-declared-gate", "Proof ran on a different gate."))

                if gate is None:
                    findings.append(_finding("missing-enforcement-observation", "No workflow/ruleset observation was supplied."))
                else:
                    if not gate.declared_blocking:
                        findings.append(_finding("gate-not-declared-blocking", "Gate is not declared blocking."))
                    if not gate.workflow_required:
                        findings.append(_finding("gate-not-in-workflow-aggregation", "Gate does not reach merge aggregation."))
                    if not gate.live_required or not gate.required_context:
                        findings.append(_finding("gate-not-live-required", "No live required status context enforces the gate."))

                if any(item["code"] == "proof-not-passed" for item in findings):
                    state = "regressed"
                elif findings:
                    target_met = detector is not None and detector.current == detector.target and not detector.findings
                    exact = proof is not None and proof.result == "passed" and proof.target_sha == target_sha
                    state = "proven" if target_met and exact else "active"
                else:
                    state = "enforced"

                row = {
                    "id": guarantee_id,
                    "initiative_id": initiative_id,
                    "statement": guarantee.statement,
                    "affected_acs": list(guarantee.affected_acs),
                    "test_refs": [roadmap[ac_id].test for ac_id in guarantee.affected_acs],
                    "detector": guarantee.detector,
                    "target_label": guarantee.target,
                    "current": detector.current if detector else None,
                    "target": detector.target if detector else None,
                    "state": state,
                    "findings": findings,
                    "proof": proof.model_dump(mode="json") if proof else None,
                    "enforcement": gate.model_dump(mode="json") if gate else None,
                }
                guarantee_rows[guarantee_id] = row
                initiative_findings.extend(findings)

            rows = [guarantee_rows[key] for key in guarantee_keys]
            open_count = sum(row["state"] != "enforced" for row in rows)
            blocked_count = sum(bool(row["findings"]) for row in rows)
            state = "enforced" if not initiative_findings and open_count == 0 else "active"
            if any(row["state"] == "regressed" for row in rows):
                state = "regressed"
            initiative_rows[initiative_id] = {
                "id": initiative_id,
                "package": contract.name,
                "title": initiative.title,
                "issue": initiative.issue,
                "state": state,
                "current": sum((row["current"] or 0) for row in rows),
                "target": sum((row["target"] or 0) for row in rows),
                "open_guarantees": open_count,
                "blocked_guarantees": blocked_count,
                "guarantees": guarantee_keys,
                "findings": initiative_findings,
            }

    return {
        "target_sha": target_sha,
        "observed_at": observed_at.isoformat(),
        "initiatives": initiative_rows,
        "guarantees": guarantee_rows,
    }

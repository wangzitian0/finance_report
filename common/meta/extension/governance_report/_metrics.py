"""Coverage ratios, quality snapshot, trend comparison."""

from __future__ import annotations


from common.meta.extension.governance_report._base import (
    PROTECTED_DEBT_LABELS,
    PROTECTED_RATIO_LABELS,
    RATIO_EPSILON,
)
from common.meta.extension.governance_report._types import (
    GateViolation,
    GovernanceEntry,
)
from common.meta.extension.governance_report._util import (
    _gate_target,
    _has_proof,
    _is_high_risk,
    _is_machine_owned,
)


def _field_coverage(entries: list[GovernanceEntry], field: str) -> dict[str, object]:
    missing = sorted(entry.key for entry in entries if not getattr(entry, field))
    return {
        "present": len(entries) - len(missing),
        "missing": len(missing),
        "missing_keys": missing,
    }


def _coverage_ratio(present: int, total: int) -> float:
    return 1.0 if total == 0 else present / total


def _quality_ratio(present: int, total: int) -> dict[str, float | int]:
    return {
        "present": present,
        "total": total,
        "ratio": _coverage_ratio(present, total),
    }


def _governance_quality_snapshot(
    entries: list[GovernanceEntry],
) -> dict[str, dict[str, dict[str, float | int]] | dict[str, int]]:
    machine_entries = [entry for entry in entries if _is_machine_owned(entry)]
    high_risk_entries = [entry for entry in entries if _is_high_risk(entry)]
    missing_family = [entry for entry in entries if not entry.family]
    missing_kind = [entry for entry in entries if not entry.kind]
    machine_missing_proof = [
        entry for entry in machine_entries if not _has_proof(entry)
    ]
    high_risk_missing_proof = [
        entry for entry in high_risk_entries if not _has_proof(entry)
    ]

    return {
        "ratios": {
            "manifest_family_coverage": _quality_ratio(
                len(entries) - len(missing_family),
                len(entries),
            ),
            "manifest_kind_coverage": _quality_ratio(
                len(entries) - len(missing_kind),
                len(entries),
            ),
            "machine_proof_coverage": _quality_ratio(
                len(machine_entries) - len(machine_missing_proof),
                len(machine_entries),
            ),
            "high_risk_proof_coverage": _quality_ratio(
                len(high_risk_entries) - len(high_risk_missing_proof),
                len(high_risk_entries),
            ),
        },
        "debts": {
            "missing_family": len(missing_family),
            "missing_kind": len(missing_kind),
            "machine_owner_entries_missing_proof": len(machine_missing_proof),
            "high_risk_entries_missing_proof": len(high_risk_missing_proof),
        },
    }


def _compare_governance_trends(
    system: str,
    base_entries: list[GovernanceEntry],
    current_entries: list[GovernanceEntry],
) -> tuple[int, list[GateViolation]]:
    """Compare protected #823 quality ratios and debt counts for one system."""

    base_snapshot = _governance_quality_snapshot(base_entries)
    current_snapshot = _governance_quality_snapshot(current_entries)
    base_ratios = base_snapshot["ratios"]
    current_ratios = current_snapshot["ratios"]
    base_debts = base_snapshot["debts"]
    current_debts = current_snapshot["debts"]
    violations: list[GateViolation] = []
    check_count = 0

    for metric, label in PROTECTED_RATIO_LABELS.items():
        check_count += 1
        base_metric = base_ratios[metric]
        current_metric = current_ratios[metric]
        base_ratio = float(base_metric["ratio"])
        current_ratio = float(current_metric["ratio"])
        if current_ratio + RATIO_EPSILON >= base_ratio:
            continue
        violations.append(
            GateViolation(
                code="governance_ratio_decreased",
                system=system,
                target=_gate_target(system, f"ratio:{metric}"),
                message=(
                    f"{label} decreased ({base_ratio:.4f} -> {current_ratio:.4f}). "
                    "#823 requires protected SSOT governance ratios to be "
                    "non-decreasing."
                ),
            )
        )

    for metric, label in PROTECTED_DEBT_LABELS.items():
        check_count += 1
        base_count = int(base_debts[metric])
        current_count = int(current_debts[metric])
        if current_count <= base_count:
            continue
        violations.append(
            GateViolation(
                code="governance_debt_increased",
                system=system,
                target=_gate_target(system, f"debt:{metric}"),
                message=(
                    f"{label} increased ({base_count} -> {current_count}). "
                    "#823 requires protected SSOT debt counts to be "
                    "non-increasing."
                ),
            )
        )

    return check_count, violations


def _future_candidate(code: str, count: int, sample: object) -> dict[str, object]:
    return {"code": code, "count": count, "sample": sample}

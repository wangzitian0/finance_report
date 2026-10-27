"""Live structural detector for cash-event projection governance."""

from __future__ import annotations

from pathlib import Path

from common.meta.base.detector_runner import read_source, requires, run_detectors

_CASH_FLOW = "apps/backend/src/reporting/extension/cash_flow.py"
_REPORTING_INIT = "apps/backend/src/reporting/__init__.py"
_CONTRACT = "common/reporting/contract.py"
_TEST_PROJECTION = "apps/backend/tests/reporting/test_cash_event_projection.py"
_TEST_GOVERNANCE = "apps/backend/tests/reporting/test_cash_event_governance.py"

GOVERNANCE_SOURCE_PATHS = (
    _CASH_FLOW,
    _REPORTING_INIT,
    _CONTRACT,
    _TEST_PROJECTION,
    _TEST_GOVERNANCE,
)

_PROJECTION_OWNER = requires(
    _REPORTING_INIT,
    '"generate_cash_flow": "src.reporting.extension.cash_flow"',
    '"generate_cash_flow",',
)


def _one_projection_owner(repo_root: Path) -> list[str]:
    findings = _PROJECTION_OWNER(repo_root)
    source = read_source(repo_root, _REPORTING_INIT)
    if "generate_cash_flow_legacy" in source or "generate_cash_flow_v2" in source:
        findings.append(
            f"{_REPORTING_INIT}: multiple parallel cash flow generators detected"
        )
    return findings


_CHECKS = {
    "cash-touch-only": requires(
        _CASH_FLOW,
        "cash_lines = tuple(pair for pair in lines if pair[1].id in cash_account_ids)",
        "if not cash_lines:",
        "continue",
        "has_cash_leg = exists(",
        "cash_line.account_id.in_(cash_account_ids)",
    ),
    "event-classification": requires(
        _CASH_FLOW,
        "has_authoritative_producer = (",
        "self.entry.source_type == JournalEntrySourceType.SYSTEM and self.has_authoritative_decision",
        "counterpart_types = {account.type for _line, account in self.counterpart_lines}",
        "if counterpart_types and counterpart_types <= {AccountType.INCOME, AccountType.EXPENSE}:",
        'return "Operating"',
        "return None",
    ),
    "transfer-neutrality": requires(
        _CASH_FLOW,
        "selected_ids.update(",
        "account.is_system and account.code == _PROCESSING_ACCOUNT.code and account.type == AccountType.ASSET",
        "movement = sum(",
        'if movement == Decimal("0"):',
        "continue",
    ),
    "cash-bridge": requires(
        _CASH_FLOW, "calculate_cash_flow_bridge(", '"cash_bridge": {'
    ),
    "dual-tenant-isolation": requires(
        _CASH_FLOW,
        "where(foreign_account.user_id != user_id)",
        ".where(JournalEntry.user_id == user_id)",
        ".where(Account.user_id == user_id)",
        ".where(~has_foreign_account)",
    ),
    "one-projection-owner": _one_projection_owner,
    "consumer-proof-state": requires(
        _CASH_FLOW,
        '"proof_state": "proven" if not proof_reasons else "unproven"',
        '"proof_reasons": sorted(proof_reasons)',
        'proof_reasons.add("cash_identity_compatibility_fallback")',
        'proof_reasons.add("cash_event_decision_unproven")',
        'proof_reasons.add("cash_event_classification_ambiguous")',
    ),
    "event-lineage": requires(
        _CASH_FLOW,
        '"journal_entry_id": event.entry.id,',
        '"source_type": event.entry.source_type.value,',
        '"source_id": event.entry.source_id,',
        '"decision_anchor_id": event.entry.decision_anchor_id,',
        '"decision_authority_state": event.entry.decision_authority_state.value,',
        '"event_types": sorted({line.event_type for line, _account in all_lines if line.event_type is not None}),',
    ),
    "exact-governance-detail": requires(
        _CONTRACT,
        'issue="https://github.com/wangzitian0/finance_report/issues/1996"',
        'id="authoritative-cash-event-projection"',
        'required_proof_strength="value-oracle"',
        'required_proof_strength="exact"',
        'enforcing_gate="ci.backend"',
        "AC-reporting.cash-events.10",
    ),
    "counterfactual-lock": requires(
        _TEST_PROJECTION,
        'voided.void_reason = "Counterfactual fixture"',
        'assert report["event_lineage"][0]["journal_entry_id"] != voided.id',
        '"cash_event_classification_ambiguous"',
    ),
}


def detect_governance(*, repo_root: Path) -> list[dict[str, object]]:
    """Scan reporting cash-event projection invariants and emit detector observations."""
    return run_detectors("reporting", _CHECKS, repo_root)


__all__ = ["GOVERNANCE_SOURCE_PATHS", "detect_governance"]

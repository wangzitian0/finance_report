"""Live structural detector for cash-event projection governance."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

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


def _source(repo_root: Path, relative: str) -> str:
    path = repo_root / relative
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _contains(repo_root: Path, relative: str, fragments: tuple[str, ...]) -> list[str]:
    path = repo_root / relative
    if not path.is_file():
        return [f"{relative}: file does not exist"]
    try:
        raw_source = path.read_text(encoding="utf-8")
    except Exception as exc:
        return [f"{relative}: failed to read: {exc}"]
    source = " ".join(raw_source.split())
    return [
        f"{relative}: missing {fragment}"
        for fragment in fragments
        if " ".join(fragment.split()) not in source
    ]


def _cash_touch_only(repo_root: Path) -> list[str]:
    return _contains(
        repo_root,
        _CASH_FLOW,
        (
            "cash_lines = tuple(pair for pair in lines if pair[1].id in cash_account_ids)",
            "if not cash_lines:",
            "continue",
            "has_cash_leg = exists(",
            "cash_line.account_id.in_(cash_account_ids)",
        ),
    )


def _event_classification(repo_root: Path) -> list[str]:
    return _contains(
        repo_root,
        _CASH_FLOW,
        (
            "has_authoritative_producer = (",
            "self.entry.source_type == JournalEntrySourceType.SYSTEM and self.has_authoritative_decision",
            "counterpart_types = {account.type for _line, account in self.counterpart_lines}",
            "if counterpart_types and counterpart_types <= {AccountType.INCOME, AccountType.EXPENSE}:",
            'return "Operating"',
            "return None",
        ),
    )


def _transfer_neutrality(repo_root: Path) -> list[str]:
    return _contains(
        repo_root,
        _CASH_FLOW,
        (
            "selected_ids.update(",
            "account.is_system and account.code == _PROCESSING_ACCOUNT.code and account.type == AccountType.ASSET",
            "movement = sum(",
            'if movement == Decimal("0"):',
            "continue",
        ),
    )


def _cash_bridge(repo_root: Path) -> list[str]:
    return _contains(
        repo_root,
        _CASH_FLOW,
        (
            "bridge_total = _quantize_money(classified_activity + unclassified_cash + fx_effect + opening_stock_adjustment)",
            "discrepancy = _quantize_money(cash_delta - bridge_total)",
            'reconciles = discrepancy == Decimal("0.00")',
            '"cash_bridge": {',
        ),
    )


def _dual_tenant_isolation(repo_root: Path) -> list[str]:
    return _contains(
        repo_root,
        _CASH_FLOW,
        (
            "where(foreign_account.user_id != user_id)",
            ".where(JournalEntry.user_id == user_id)",
            ".where(Account.user_id == user_id)",
            ".where(~has_foreign_account)",
        ),
    )


def _one_projection_owner(repo_root: Path) -> list[str]:
    findings = _contains(
        repo_root,
        _REPORTING_INIT,
        (
            '"generate_cash_flow": "src.reporting.extension.cash_flow"',
            '"generate_cash_flow",',
        ),
    )
    source = _source(repo_root, _REPORTING_INIT)
    if "generate_cash_flow_legacy" in source or "generate_cash_flow_v2" in source:
        findings.append(
            f"{_REPORTING_INIT}: multiple parallel cash flow generators detected"
        )
    return findings


def _consumer_proof_state(repo_root: Path) -> list[str]:
    return _contains(
        repo_root,
        _CASH_FLOW,
        (
            '"proof_state": "proven" if not proof_reasons else "unproven"',
            '"proof_reasons": sorted(proof_reasons)',
            'proof_reasons.add("cash_identity_compatibility_fallback")',
            'proof_reasons.add("cash_event_decision_unproven")',
            'proof_reasons.add("cash_event_classification_ambiguous")',
        ),
    )


def _event_lineage(repo_root: Path) -> list[str]:
    return _contains(
        repo_root,
        _CASH_FLOW,
        (
            '"journal_entry_id": event.entry.id,',
            '"source_type": event.entry.source_type.value,',
            '"source_id": event.entry.source_id,',
            '"decision_anchor_id": event.entry.decision_anchor_id,',
            '"decision_authority_state": event.entry.decision_authority_state.value,',
            '"event_types": sorted({line.event_type for line, _account in all_lines if line.event_type is not None}),',
        ),
    )


def _exact_governance_detail(repo_root: Path) -> list[str]:
    return _contains(
        repo_root,
        _CONTRACT,
        (
            'issue="https://github.com/wangzitian0/finance_report/issues/1996"',
            'id="authoritative-cash-event-projection"',
            'required_proof_strength="value-oracle"',
            'required_proof_strength="exact"',
            'enforcing_gate="ci.backend"',
            "AC-reporting.cash-events.10",
        ),
    )


def _counterfactual_lock(repo_root: Path) -> list[str]:
    return _contains(
        repo_root,
        _TEST_PROJECTION,
        (
            'voided.void_reason = "Counterfactual fixture"',
            'assert report["event_lineage"][0]["journal_entry_id"] != voided.id',
            '"cash_event_classification_ambiguous"',
        ),
    )


_CHECKS: tuple[tuple[str, Callable[[Path], list[str]]], ...] = (
    ("cash-touch-only", _cash_touch_only),
    ("event-classification", _event_classification),
    ("transfer-neutrality", _transfer_neutrality),
    ("cash-bridge", _cash_bridge),
    ("dual-tenant-isolation", _dual_tenant_isolation),
    ("one-projection-owner", _one_projection_owner),
    ("consumer-proof-state", _consumer_proof_state),
    ("event-lineage", _event_lineage),
    ("exact-governance-detail", _exact_governance_detail),
    ("counterfactual-lock", _counterfactual_lock),
)


def detect_governance(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """Scan reporting cash-event projection invariants and emit detector observations."""
    resolved_root = (
        repo_root
        if repo_root is not None
        else Path(__file__).resolve().parent.parent.parent.parent
    )
    observations: list[dict[str, Any]] = []
    for guarantee_id, check in _CHECKS:
        try:
            findings = check(resolved_root)
        except (OSError, SyntaxError, UnicodeError) as exc:
            findings = [
                f"{guarantee_id}: source inspection failed ({type(exc).__name__}): {exc}"
            ]
        observations.append(
            {
                "guarantee_id": f"reporting/{guarantee_id}",
                "current": len(findings),
                "target": 0,
                "findings": findings,
            }
        )
    return observations


__all__ = ["GOVERNANCE_SOURCE_PATHS", "detect_governance"]

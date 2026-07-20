"""Canonical semantic capability registry for product source classes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SourceCapabilityStatus(StrEnum):
    """Product support state; proof execution remains testing-owned."""

    SUPPORTED = "supported"
    MANUAL_TRUSTED = "manual_trusted"
    GAP = "gap"


def _text(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


@dataclass(frozen=True, slots=True)
class SourceCapability:
    """One source class's semantic product contract, independent of tests."""

    capability_id: str
    status: SourceCapabilityStatus
    intake_modes: tuple[str, ...]
    evidence_kinds: tuple[str, ...]
    produced_facts: tuple[str, ...]
    review_semantics: str
    traceability_target: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability_id", _text(self.capability_id, "capability_id"))
        if not isinstance(self.status, SourceCapabilityStatus):
            raise TypeError("status must be SourceCapabilityStatus")
        for name in ("intake_modes", "evidence_kinds", "produced_facts"):
            values = getattr(self, name)
            if not values or any(not item.strip() for item in values):
                raise ValueError(f"{name} requires semantic identifiers")
            if any("pytest" in item.lower() or "::test" in item.lower() for item in values):
                raise ValueError("SourceCapability cannot own test paths")
        _text(self.review_semantics, "review_semantics")
        _text(self.traceability_target, "traceability_target")


SOURCE_CAPABILITIES: tuple[SourceCapability, ...] = (
    SourceCapability(
        capability_id="bank_statement",
        status=SourceCapabilityStatus.SUPPORTED,
        intake_modes=("pdf", "image"),
        evidence_kinds=("bank_statement",),
        produced_facts=("statement_balance", "transaction"),
        review_semantics="missing or invalid source facts require statement review",
        traceability_target="statement-extraction-result",
    ),
    SourceCapability(
        capability_id="brokerage_statement",
        status=SourceCapabilityStatus.SUPPORTED,
        intake_modes=("pdf", "image", "csv"),
        evidence_kinds=("brokerage_statement", "position_snapshot"),
        produced_facts=("position", "brokerage_transaction", "declared_balance"),
        review_semantics="positions may parse without a cash ladder and remain review-only",
        traceability_target="statement-extraction-result",
    ),
    SourceCapability(
        capability_id="csv_export",
        status=SourceCapabilityStatus.MANUAL_TRUSTED,
        intake_modes=("csv",),
        evidence_kinds=("transaction_export",),
        produced_facts=("transaction",),
        review_semantics=("missing statement identity, currency, period, or balances require human confirmation"),
        traceability_target="statement-extraction-result",
    ),
    SourceCapability(
        capability_id="settlement_note",
        status=SourceCapabilityStatus.GAP,
        intake_modes=("pdf", "csv"),
        evidence_kinds=("settlement_note",),
        produced_facts=("lot", "fee", "dividend"),
        review_semantics="unsupported until structured settlement facts reach extraction",
        traceability_target="settlement-note-to-investment-schedule",
    ),
    SourceCapability(
        capability_id="esop_rsu_plan",
        status=SourceCapabilityStatus.MANUAL_TRUSTED,
        intake_modes=("manual_evidence", "structured_payload"),
        evidence_kinds=("grant_document", "vesting_schedule"),
        produced_facts=("grant", "vesting_event", "unlock_basis"),
        review_semantics="explicit manual evidence must identify vesting and unlock basis",
        traceability_target="manual-restricted-compensation-to-annualized-schedule",
    ),
    SourceCapability(
        capability_id="property_statement",
        status=SourceCapabilityStatus.MANUAL_TRUSTED,
        intake_modes=("manual_evidence", "structured_payload"),
        evidence_kinds=("appraisal", "property_statement"),
        produced_facts=("property_valuation",),
        review_semantics="explicit manual evidence must identify valuation basis and as-of date",
        traceability_target="manual-property-valuation-to-balance-sheet-line",
    ),
    SourceCapability(
        capability_id="liability_statement",
        status=SourceCapabilityStatus.MANUAL_TRUSTED,
        intake_modes=("manual_evidence", "structured_payload"),
        evidence_kinds=(
            "loan_statement",
            "credit_card_statement",
            "mortgage_statement",
        ),
        produced_facts=("liability_balance",),
        review_semantics="explicit manual input or reviewed statement evidence is required",
        traceability_target="liability-source-to-balance-sheet-liability-line",
    ),
    SourceCapability(
        capability_id="manual_record",
        status=SourceCapabilityStatus.MANUAL_TRUSTED,
        intake_modes=("api_entry", "manual_evidence"),
        evidence_kinds=("user_supplied_record",),
        produced_facts=("balanced_journal_command",),
        review_semantics="explicit user input and a balanced Decimal command are required",
        traceability_target="manual-entry-to-ledger-to-report-line",
    ),
)

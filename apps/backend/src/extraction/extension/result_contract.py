"""Adapter from provider payloads into the extraction package result contract."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal

from src.extraction.base.result import (
    ExtractedPositionFact,
    ExtractedTransactionFact,
    ExtractionMethod,
    SourceProvenance,
    StatementBalanceFact,
    StatementEvidenceType,
    StatementExtractionResult,
    StatementSourceType,
)
from src.extraction.base.types import DocumentSource, ExtractedTransactionRow
from src.extraction.extension.brokerage_positions import BrokeragePositionSnapshot
from src.extraction.orm.statement_summary import StatementSummary


def _position_id(position: BrokeragePositionSnapshot) -> str:
    payload = {
        "date": position.snapshot_date.isoformat() if position.snapshot_date is not None else None,
        "symbol": position.asset_identifier,
        "broker": position.broker,
        "currency": position.currency,
        "quantity": str(position.quantity),
        "market_value": str(position.market_value),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _period(
    statement: StatementSummary,
    positions: list[BrokeragePositionSnapshot],
) -> tuple[date | None, date | None]:
    if statement.period_start is not None and statement.period_end is not None:
        return statement.period_start, statement.period_end
    snapshot_dates = {position.snapshot_date for position in positions if position.snapshot_date is not None}
    if len(snapshot_dates) == 1:
        snapshot_date = next(iter(snapshot_dates))
        return snapshot_date, snapshot_date
    return None, None


def statement_evidence_type(
    *,
    is_brokerage: bool,
    provider_payload: dict,
    positions: list[BrokeragePositionSnapshot],
) -> StatementEvidenceType:
    """Classify the source shape once, after the brokerage payload is normalized."""
    if not is_brokerage:
        return StatementEvidenceType.TRANSACTION_LEDGER
    statement = provider_payload.get("statement")
    declared_position_snapshot = any(key in provider_payload for key in ("positions", "holdings", "securities"))
    if isinstance(statement, dict):
        declared_position_snapshot = declared_position_snapshot or any(
            key in statement for key in ("positions", "holdings", "securities")
        )
    return (
        StatementEvidenceType.POSITION_SNAPSHOT
        if declared_position_snapshot or positions
        else StatementEvidenceType.TRANSACTION_LEDGER
    )


def _balances(statement: StatementSummary) -> tuple[StatementBalanceFact, ...]:
    if statement.currency_balances:
        return tuple(
            StatementBalanceFact(
                currency=item["currency"],
                opening=Decimal(str(item["opening"])),
                closing=Decimal(str(item["closing"])),
            )
            for item in statement.currency_balances
        )
    if not statement.currency or statement.opening_balance is None or statement.closing_balance is None:
        return ()
    return (
        StatementBalanceFact(
            currency=statement.currency,
            opening=statement.opening_balance,
            closing=statement.closing_balance,
        ),
    )


def build_statement_extraction_result(
    *,
    source: DocumentSource,
    file_type: str,
    statement: StatementSummary,
    transactions: list[ExtractedTransactionRow],
    provider_payload: dict,
    model: str,
    provider: str,
    method: ExtractionMethod,
    is_brokerage: bool,
    evidence_type: StatementEvidenceType,
    positions: list[BrokeragePositionSnapshot],
) -> StatementExtractionResult:
    """Close every provider path over one strict, digest-addressed result."""
    period_start, period_end = _period(statement, positions)
    validation_reason = (statement.validation_error or "").strip()
    raw_warnings = provider_payload.get("warnings")
    warnings = tuple(str(value) for value in raw_warnings) if isinstance(raw_warnings, list) else ()
    return StatementExtractionResult.create(
        producer_version=f"extractor:{model}",
        source_content_digest=source.content_hash,
        source_type=StatementSourceType.BROKERAGE if is_brokerage else StatementSourceType.BANK,
        evidence_type=evidence_type,
        institution=statement.institution,
        account_last4=statement.account_last4,
        period_start=period_start,
        period_end=period_end,
        balances=_balances(statement),
        transactions=tuple(
            ExtractedTransactionFact(
                fact_id=row.dedup_hash,
                transaction_date=row.txn_date,
                description=row.description,
                amount=row.amount,
                direction=row.direction,
                currency=None if row.currency_unresolved else row.currency,
                balance_after=row.balance_after,
                confidence=None,
            )
            for row in transactions
        ),
        positions=tuple(
            ExtractedPositionFact(
                fact_id=_position_id(position),
                symbol=position.asset_identifier,
                quantity=position.quantity,
                market_value=position.market_value,
                currency=position.currency,
                confidence=None,
                asset_type=position.asset_type.value if position.asset_type else None,
                sector=position.sector,
                geography=position.geography,
            )
            for position in positions
        ),
        confidence=Decimal(statement.confidence_score or 0) / Decimal("100"),
        balance_validated=statement.balance_validated,
        warnings=warnings,
        review_reasons=(validation_reason,) if validation_reason else (),
        provenance=SourceProvenance(
            intake_mode=file_type,
            method=method,
            provider=provider,
            model=model,
        ),
        statement_currency=statement.currency,
    )

"""Brokerage-statement import payload assembly.

Pure domain helpers that build or recover the import payload consumed by
``BrokeragePositionImportService`` from a parsed brokerage statement, its
transactions, and persisted OCR extraction metadata, plus the not-ready-reason
message. Extracted from the statements router so the router stays a thin HTTP
layer; behavior unchanged.
"""

from __future__ import annotations

from typing import Any, cast

from src.extraction.base.result import StatementExtractionResult
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_enums import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary


def reject_json_floats(value: object, path: str) -> None:
    """Reject JSON floats anywhere in an import payload (money wire policy).

    ``bool``/``int`` stay allowed (exact); a float anywhere in the brokerage
    payload would launder IEEE-754 precision into position quantities or
    market values via the importer's ``str(value)`` coercion (#1864 S1,
    AC-portfolio.brokerage-import.10). Iterative (explicit stack) so a deeply
    nested payload cannot trigger ``RecursionError``.
    """
    stack: list[tuple[object, str]] = [(value, path)]
    while stack:
        current, at = stack.pop()
        if isinstance(current, float):
            raise ValueError(f"{at}: JSON floats are not allowed; encode amounts as decimal strings")
        if isinstance(current, dict):
            stack.extend((item, f"{at}.{key}") for key, item in current.items())
        elif isinstance(current, list):
            stack.extend((item, f"{at}[{index}]") for index, item in enumerate(current))


def _brokerage_payload_from_statement(
    statement: StatementSummary,
    transactions: list[AtomicTransaction],
) -> dict:
    """Build an import payload from a parsed brokerage statement."""
    events = []
    for txn in transactions:
        direction = txn.direction.value if hasattr(txn.direction, "value") else txn.direction
        signed_amount = txn.amount if direction == "IN" else -txn.amount
        events.append(
            {
                "date": txn.txn_date.isoformat(),
                "description": txn.description,
                "amount": str(signed_amount),
                "currency": txn.currency or statement.currency,
                "raw_text": txn.description,
            }
        )

    return {
        "institution": statement.institution,
        "statement": {
            "institution": statement.institution,
            "period_end": statement.period_end.isoformat() if statement.period_end else None,
            "currency": statement.currency,
        },
        "transactions": events,
        "events": events,
    }


def _extract_brokerage_payload_from_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the structured extraction payload stored in Layer 1 metadata."""
    if not isinstance(metadata, dict):
        return None
    payload = metadata.get("statement_extraction_result")
    if not isinstance(payload, dict):
        return None
    result = StatementExtractionResult.from_payload(payload)
    return {
        "institution": result.institution,
        "statement": {
            "institution": result.institution,
            "period_start": result.period_start.isoformat() if result.period_start is not None else None,
            "period_end": result.period_end.isoformat() if result.period_end is not None else None,
            "currency": result.balances[0].currency if result.balances else None,
        },
        "balances": [
            {"currency": item.currency, "opening": str(item.opening), "closing": str(item.closing)}
            for item in result.balances
        ],
        "positions": [
            {
                "symbol": item.symbol,
                "quantity": str(item.quantity),
                "market_value": str(item.market_value),
                "currency": item.currency,
                "asset_type": item.asset_type,
                "sector": item.sector,
                "geography": item.geography,
            }
            for item in result.positions
        ],
    }


def _enrich_brokerage_payload_from_statement(payload: dict[str, Any], statement: StatementSummary) -> dict[str, Any]:
    """Backfill statement metadata into a recovered extraction payload."""
    enriched = dict(payload)
    enriched.setdefault("institution", statement.institution)
    existing_statement_payload = enriched.get("statement")
    statement_payload = (
        dict(cast(dict[str, Any], existing_statement_payload)) if isinstance(existing_statement_payload, dict) else {}
    )
    statement_payload.setdefault("institution", statement.institution)
    statement_payload.setdefault("period_end", statement.period_end.isoformat() if statement.period_end else None)
    statement_payload.setdefault("currency", statement.currency)
    enriched["statement"] = statement_payload
    return enriched


def _brokerage_payload_from_persisted_extraction(
    *,
    statement: StatementSummary,
    uploaded_document: UploadedDocument | None,
) -> dict | None:
    """Load the persisted OCR extraction payload for statement-scoped imports."""
    payload = _extract_brokerage_payload_from_metadata(statement.extraction_metadata)
    if payload is not None:
        return _enrich_brokerage_payload_from_statement(payload, statement)

    if uploaded_document is None:
        return None
    payload = _extract_brokerage_payload_from_metadata(uploaded_document.extraction_metadata)
    if payload is None:
        return None
    return _enrich_brokerage_payload_from_statement(payload, statement)


def _brokerage_import_not_ready_reason(statement: StatementSummary, transaction_count: int) -> str:
    """Explain why a brokerage statement cannot be imported yet."""
    status_value = statement.status.value if hasattr(statement.status, "value") else str(statement.status)
    validation_error = statement.validation_error

    if status_value == BankStatementStatus.REJECTED.value:
        return f"Provider parsing failed before brokerage import: {validation_error or 'statement rejected'}"
    if status_value in {BankStatementStatus.UPLOADED.value, BankStatementStatus.PARSING.value}:
        return "Provider parsing has not completed; statement must be parsed before brokerage import"

    return f"Statement must be parsed before importing brokerage positions; current status={status_value}"

"""Brokerage-statement import payload assembly.

Pure domain helpers that build or recover the import payload consumed by
``BrokeragePositionImportService`` from a parsed brokerage statement, its
transactions, and persisted OCR extraction metadata, plus the not-ready-reason
message. Extracted from the statements router so the router stays a thin HTTP
layer; behavior unchanged.
"""

from __future__ import annotations

from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_enums import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary


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


def _extract_brokerage_payload_from_metadata(metadata: dict | None) -> dict | None:
    """Return the structured extraction payload stored in Layer 1 metadata."""
    if not isinstance(metadata, dict):
        return None
    for key in ("extraction_payload", "parsed_payload", "payload"):
        payload = metadata.get(key)
        if isinstance(payload, dict):
            return payload
    return metadata if any(key in metadata for key in ("positions", "holdings", "securities")) else None


def _enrich_brokerage_payload_from_statement(payload: dict, statement: StatementSummary) -> dict:
    """Backfill statement metadata into a recovered extraction payload."""
    enriched = dict(payload)
    enriched.setdefault("institution", statement.institution)
    statement_payload = enriched.get("statement") if isinstance(enriched.get("statement"), dict) else {}
    statement_payload = dict(statement_payload)
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

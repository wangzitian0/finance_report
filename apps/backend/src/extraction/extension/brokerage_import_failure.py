"""The record of a failed brokerage import on its statement (#2648).

A failed ``POST /statements/{id}/brokerage/import`` keeps the statement ``parsed`` and records the
failure in ``extraction_metadata[BROKERAGE_IMPORT_FAILURE_KEY]``: the reason, the request id and the
time. ``validation_error`` does not change, so an earlier note stays and a later write of that note
(an envelope confirmation, a blocked approval) keeps the record. Only a successful import removes
it. A re-parse writes new extraction metadata, so the record of the old extraction goes with it.

The writes are one SQL ``UPDATE`` each: they change only the record key of the stored metadata.
The session expires the metadata of a loaded statement after the write, so a later read sees it.
A concurrent write of the other keys (for example a re-parse) is not lost, and an import that
loaded the statement before another import failed still clears that failure when it succeeds.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, literal, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.base.source_vocabulary import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary

#: The ``extraction_metadata`` key of the last failed brokerage import. Its value holds ``reason``,
#: ``request_id`` and ``failed_at``.
BROKERAGE_IMPORT_FAILURE_KEY = "brokerage_import_failure"
#: The reason of a failed import that has no specific reason (a server fault).
BROKERAGE_IMPORT_FAILED_MESSAGE = "The positions could not be imported. Retry, or delete the file and upload it again."
#: The statuses that allow a brokerage import (``POST /statements/{id}/brokerage/import``).
BROKERAGE_IMPORTABLE_STATUSES = (BankStatementStatus.PARSED, BankStatementStatus.APPROVED)


def _stored_metadata_object() -> Any:
    """The stored metadata as a JSON object. SQL NULL or a JSON scalar reads as ``{}``."""
    column = StatementSummary.extraction_metadata
    return case((func.jsonb_typeof(column) == "object", column), else_=literal({}, JSONB))


async def record_brokerage_import_failure(
    db: AsyncSession, *, statement_id: UUID, user_id: UUID, reason: str | None, request_id: str | None
) -> None:
    """Record a failed brokerage import on the statement.

    A rejected source has a specific reason (HTTP 422, #2649): the record states it, so the upload
    list shows the remedy. Without a reason (a server fault), it states
    ``BROKERAGE_IMPORT_FAILED_MESSAGE``. The caller owns the transaction: it rolls back the failed
    import first, then commits this write in a new transaction.
    """
    text = reason.strip()[:500] if reason and reason.strip() else BROKERAGE_IMPORT_FAILED_MESSAGE
    record = {
        BROKERAGE_IMPORT_FAILURE_KEY: {
            "reason": text,
            "request_id": request_id,
            "failed_at": datetime.now(UTC).isoformat(),
        }
    }
    await db.execute(
        update(StatementSummary)
        .where(StatementSummary.id == statement_id, StatementSummary.user_id == user_id)
        .values(extraction_metadata=_stored_metadata_object().op("||", return_type=JSONB)(literal(record, JSONB)))
        .execution_options(synchronize_session="fetch")
    )


async def clear_brokerage_import_failure(db: AsyncSession, *, statement_id: UUID, user_id: UUID) -> None:
    """Remove the record of a failed import, in the transaction of the successful import.

    It removes only the record key of the stored metadata, so a concurrent write of the other keys
    stays. It also removes a failure that another import recorded after this import loaded the
    statement: this import succeeded later.
    """
    column = StatementSummary.extraction_metadata
    await db.execute(
        update(StatementSummary)
        .where(
            StatementSummary.id == statement_id,
            StatementSummary.user_id == user_id,
            func.jsonb_typeof(column) == "object",
            column.has_key(BROKERAGE_IMPORT_FAILURE_KEY),
        )
        .values(extraction_metadata=column.op("-", return_type=JSONB)(literal(BROKERAGE_IMPORT_FAILURE_KEY)))
        .execution_options(synchronize_session="fetch")
    )


def brokerage_import_failure_reason(statement: StatementSummary) -> str | None:
    """The reason of the last failed brokerage import of the statement, or None.

    Only a ``parsed`` or ``approved`` statement can be imported, so only such a statement reports a
    failure. A rejected or parsing statement shows its own state.
    """
    if statement.status not in BROKERAGE_IMPORTABLE_STATUSES:
        return None
    metadata = statement.extraction_metadata
    record = metadata.get(BROKERAGE_IMPORT_FAILURE_KEY) if isinstance(metadata, dict) else None
    reason = record.get("reason") if isinstance(record, dict) else None
    return reason if isinstance(reason, str) and reason else None

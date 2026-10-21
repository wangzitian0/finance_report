"""Change detection for the inputs of workflow event derivation (#2583).

Workflow derivation reads statements, reconciliation state, and package readiness. Package
readiness reads the ledger, extraction, pricing, portfolio, and audit tables. The fingerprint
covers every table in the model metadata. A table is excluded only when derivation does not
read it, or when the derivation writes it. Thus a new table is an input until a person
classifies it here, and a missed input cannot keep an event stale.

Per table, the fingerprint holds the row count and the sum of the row timestamps in the scope
of the user. An insert or a delete changes the count. An update changes ``updated_at``, so it
changes the sum. The fingerprint also holds the date, because readiness evaluates "today", and
a digest of the settings, because a deploy or a configuration change can change derivation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from uuid import UUID

from sqlalchemy import Table, and_, func, literal, select, true, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from src.config import settings
from src.database import Base

# Increment when the fingerprint shape changes, so that every stored fingerprint becomes stale.
SOURCE_FINGERPRINT_VERSION = 1

# Tables that workflow derivation does not read, or that the derivation writes itself.
# A table that the derivation writes must stay out: otherwise each derivation makes its own
# fingerprint stale.
EXCLUDED_SOURCE_TABLES: dict[str, str] = {
    "workflow_events": "The derivation writes workflow events.",
    "workflow_sessions": "The derivation writes workflow sessions.",
    "workflow_sync_states": "The derivation writes its own sync state.",
    "chat_sessions": "Advisor chat history is not a derivation input.",
    "chat_messages": "Advisor chat history is not a derivation input.",
    "ai_feedback": "User feedback on AI output is not a derivation input.",
    "counter_tally": "The counter package is not a derivation input.",
    "outbox": "The integration outbox is not a derivation input.",
    "ping_state": "The liveness ping is not a derivation input.",
}

# Tables without a ``user_id`` column that belong to one user through a parent row.
# Value: (foreign-key column, parent table with ``user_id``).
OWNER_JOINED_SOURCE_TABLES: dict[str, tuple[str, str]] = {
    "journal_lines": ("journal_entry_id", "journal_entries"),
    "journal_audit_log": ("entry_id", "journal_entries"),
    "reconciliation_matches": ("atomic_txn_id", "atomic_transactions"),
    "reconciliation_match_journal_entries": ("journal_entry_id", "journal_entries"),
    "transaction_classification": ("atomic_txn_id", "atomic_transactions"),
    "atomic_transaction_source_documents": ("uploaded_document_id", "uploaded_documents"),
    "atomic_position_source_documents": ("uploaded_document_id", "uploaded_documents"),
}

# Audit tables that hold the user in a tenant trace scope.
TENANT_SCOPED_SOURCE_TABLES = frozenset({"trace_records", "trace_record_parents"})

# Tables that are not owned by one user. The fingerprint reads the full table.
# An unclassified table without ``user_id`` also falls to this full-table read.
GLOBAL_SOURCE_TABLES = frozenset(
    {
        "app_config",
        "fx_rates",
        "market_data_sync_state",
        "reconciliation_transfer_pair_legs",
        "reconciliation_transfer_pairs",
        "stock_prices",
    }
)

_USERS_TABLE = "users"


def _row_stamp(table: Table):
    column = table.c.get("updated_at")
    if column is None:
        column = table.c.get("created_at")
    if column is None:
        return literal(0)
    return func.coalesce(func.sum(func.extract("epoch", column)), 0)


def _source_select(table: Table, user_id: UUID) -> Select:
    name = table.name
    source = select(
        literal(name).label("source"),
        func.count().label("row_count"),
        _row_stamp(table).label("row_stamp"),
    )
    if name == _USERS_TABLE:
        return source.select_from(table).where(table.c.id == user_id)
    if "user_id" in table.c:
        return source.select_from(table).where(table.c.user_id == user_id)
    if name in OWNER_JOINED_SOURCE_TABLES:
        column, parent_name = OWNER_JOINED_SOURCE_TABLES[name]
        parent = Base.metadata.tables[parent_name]
        return source.select_from(table.join(parent, parent.c.id == table.c[column])).where(parent.c.user_id == user_id)
    if name in TENANT_SCOPED_SOURCE_TABLES:
        return source.select_from(table).where(and_(table.c.scope_kind == "TENANT", table.c.scope_id == str(user_id)))
    return source.select_from(table).where(true())


def source_tables() -> list[Table]:
    """Return the tables that the fingerprint reads, in a stable order."""
    return [table for name, table in sorted(Base.metadata.tables.items()) if name not in EXCLUDED_SOURCE_TABLES]


async def workflow_source_fingerprint(db: AsyncSession, *, user_id: UUID) -> str:
    """Return a digest that changes when any input of workflow derivation for the user changes.

    The function sends one SQL statement and writes nothing.
    """
    statement = union_all(*(_source_select(table, user_id) for table in source_tables()))
    rows = sorted((row.source, int(row.row_count), str(row.row_stamp)) for row in await db.execute(statement))
    payload = {
        "version": SOURCE_FINGERPRINT_VERSION,
        "date": date.today().isoformat(),
        "settings": hashlib.sha256(settings.model_dump_json().encode()).hexdigest(),
        "sources": rows,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

"""Measure how many rows the SELECT statements of one request read, and add other tenants (#2617).

A statement that reads the rows of other users grows with the data of those users. A report
that is fast with one user in the database is then slow on a shared database. The measure
here replays every SELECT of a request under ``EXPLAIN (ANALYZE, FORMAT JSON)`` with
``enable_seqscan = off``. With sequential scans off, the planner uses an index wherever one
exists. This models a table that is too large to scan. A statement without a usable index
still shows a sequential scan, and its row count grows with the table.

The planner statistics of the test database are empty (autovacuum is off, see ``conftest``).
This is the state of a database after a bulk load.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.extraction import (
    BankStatementStatus,
    ClassificationStatus,
    DocumentType,
    RuleType,
    Stage1Status,
    TransactionDirection,
    UploadedDocument,
)
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryAuthorityState,
    JournalEntryStatus,
    JournalLine,
)
from src.reconciliation import ReconciliationMatch, ReconciliationStatus

SCAN_NODE_TYPES = frozenset({"Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan"})
FIRST_DAY = date(2026, 1, 1)


def _add_rows_read(node: dict, totals: Counter) -> None:
    """Add the rows that the scan nodes under ``node`` read, per table."""
    if node.get("Node Type") in SCAN_NODE_TYPES and node.get("Relation Name"):
        read = (
            node.get("Actual Rows", 0)
            + node.get("Rows Removed by Filter", 0)
            + node.get("Rows Removed by Index Recheck", 0)
        ) * node.get("Actual Loops", 1)
        totals[node["Relation Name"]] += read
    for child in node.get("Plans", []):
        _add_rows_read(child, totals)


async def rows_read_by[T](db_engine, action: Callable[[], Awaitable[T]]) -> tuple[Counter, T]:
    """Run ``action`` and return the rows read per table by its SELECT statements, and its result."""
    captured: list[tuple[str, tuple]] = []

    def _capture(conn, cursor, statement, parameters, context, executemany) -> None:
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            captured.append((statement, parameters))

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        result = await action()
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)
    assert captured, "the action issued no SELECT statement"

    totals: Counter = Counter()
    async with db_engine.connect() as conn:
        await conn.exec_driver_sql("SET enable_seqscan = off")
        for statement, parameters in captured:
            plan = await conn.exec_driver_sql("EXPLAIN (ANALYZE, FORMAT JSON) " + statement, parameters)
            _add_rows_read(plan.scalar_one()[0]["Plan"], totals)
    return totals, result


async def rows_read_by_get(db_engine, client, path: str):
    """Return the rows read per table by the SELECT statements of ``GET path``, and its response."""
    totals, response = await rows_read_by(db_engine, lambda: client.get(path))
    assert response.status_code == 200, (path, response.status_code, response.text[:300])
    return totals, response


def _tenant_waves(user_id: UUID, *, entries: int, transactions: int) -> list[list]:
    """Build the rows of one tenant in three waves, so that a flush of a wave meets no missing parent.

    The tenant has posted entries, one parsed statement, classifications and accepted matches.
    """
    now = datetime.now(UTC)
    bank = Account(id=uuid4(), user_id=user_id, name="Bank", code="1001", type=AccountType.ASSET, currency="SGD")
    card = Account(id=uuid4(), user_id=user_id, name="Card", code="2001", type=AccountType.LIABILITY, currency="SGD")
    salary = Account(id=uuid4(), user_id=user_id, name="Salary", code="4001", type=AccountType.INCOME, currency="SGD")
    spending = Account(
        id=uuid4(), user_id=user_id, name="Spending", code="5001", type=AccountType.EXPENSE, currency="SGD"
    )
    accounts = [bank, card, salary, spending]
    entry_rows: list = []
    line_rows: list = []

    for index in range(entries):
        entry = JournalEntry(
            id=uuid4(),
            user_id=user_id,
            entry_date=FIRST_DAY + timedelta(days=index % 365),
            memo=f"txn {index}",
            source_type=JournalEntrySourceType.MANUAL,
            decision_authority_state=JournalEntryAuthorityState.LEGACY_UNPROVEN,
            status=JournalEntryStatus.POSTED,
        )
        credit = salary if index % 2 else spending
        entry_rows.append(entry)
        for account, direction in ((bank, Direction.DEBIT), (credit, Direction.CREDIT)):
            line_rows.append(
                JournalLine(
                    id=uuid4(),
                    journal_entry_id=entry.id,
                    account_id=account.id,
                    direction=direction,
                    amount=Decimal("100.00"),
                    currency="SGD",
                    created_at=now,
                    updated_at=now,
                )
            )

    file_hash = uuid4().hex + uuid4().hex
    document = UploadedDocument(
        id=uuid4(),
        user_id=user_id,
        file_path=f"statements/{file_hash}.pdf",
        file_hash=file_hash,
        original_filename="tenant.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    statement = StatementSummary(
        id=uuid4(),
        user_id=user_id,
        file_hash=file_hash,
        uploaded_document_id=document.id,
        institution="DBS",
        currency="SGD",
        period_start=FIRST_DAY,
        period_end=FIRST_DAY + timedelta(days=30),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
        status=BankStatementStatus.PARSED,
        stage1_status=Stage1Status.PENDING_REVIEW,
        confidence_score=95,
    )
    rule = ClassificationRule(
        id=uuid4(),
        user_id=user_id,
        created_by=user_id,
        version_number=1,
        effective_date=FIRST_DAY,
        is_active=False,
        rule_name=f"budget-{uuid4()}",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": []},
        tag_mappings={"category": "BUDGET"},
        default_account_id=spending.id,
    )
    transaction_rows: list = []
    dependent_rows: list = []
    marker = {"doc_id": str(document.id), "doc_type": DocumentType.BANK_STATEMENT.value}
    for index in range(transactions):
        transaction = AtomicTransaction(
            id=uuid4(),
            user_id=user_id,
            source_documents=[marker],
            txn_date=FIRST_DAY + timedelta(days=index % 28),
            description=f"Row {index}",
            amount=Decimal("5.00"),
            direction=TransactionDirection.OUT,
            currency="SGD",
            dedup_hash=uuid4().hex + uuid4().hex,
        )
        transaction_rows.append(transaction)
        dependent_rows.append(
            TransactionClassification(
                id=uuid4(),
                atomic_txn_id=transaction.id,
                rule_version_id=rule.id,
                account_id=spending.id,
                tags={"category": "BUDGET"},
                confidence_score=100,
                status=ClassificationStatus.APPLIED,
            )
        )
        dependent_rows.append(
            ReconciliationMatch(
                id=uuid4(),
                atomic_txn_id=transaction.id,
                journal_entry_ids=[],
                status=ReconciliationStatus.ACCEPTED,
                match_score=95,
                score_breakdown={},
            )
        )
    return [accounts + [document] + entry_rows, line_rows + [statement, rule] + transaction_rows, dependent_rows]


async def seed_tenant_rows(db: AsyncSession, user_id: UUID, *, entries: int, transactions: int) -> None:
    """Add the rows of one tenant for an existing user. Commit."""
    for wave in _tenant_waves(user_id, entries=entries, transactions=transactions):
        db.add_all(wave)
        await db.flush()
    await db.commit()


async def seed_other_tenants(db: AsyncSession, *, count: int, entries: int, transactions: int) -> None:
    """Add ``count`` more users with the rows of ``seed_tenant_rows``, in one flush. Commit."""
    users = [
        User(id=uuid4(), email=f"tenant-{index}-{uuid4()}@example.invalid", hashed_password="hashed")
        for index in range(count)
    ]
    db.add_all(users)
    await db.flush()
    waves = [_tenant_waves(user.id, entries=entries, transactions=transactions) for user in users]
    for wave_index in range(3):
        for tenant_waves in waves:
            db.add_all(tenant_waves[wave_index])
        await db.flush()
    await db.commit()

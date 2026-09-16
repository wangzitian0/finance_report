"""Run the real migration DDL against the dedicated PostgreSQL test database."""

import importlib.util
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from src.ledger import Account, AccountType, initialize_opening_positions
from src.reconciliation import ReconciliationMatch, ReconciliationStatus
from tests.factories import seed_parsed_statement


async def test_opening_migration_preserves_history_and_enforces_immutability(db, test_user):
    """AC-ledger.opening-position.7: this exercises upgrade(), not create_all's hook."""
    source = await seed_parsed_statement(db, test_user.id)
    rejected = ReconciliationMatch(
        atomic_txn_id=source.transactions[0].id,
        journal_entry_ids=[],
        status=ReconciliationStatus.REJECTED,
        match_score=70,
    )
    bank = Account(user_id=test_user.id, name="Migration synthetic bank", type=AccountType.ASSET, currency="SGD")
    db.add_all([rejected, bank])
    await db.commit()
    match_id, account_id = rejected.id, bank.id
    # Reconstruct the exact affected pre-0060 surfaces inside this test's isolated schema.
    await db.execute(text("DROP TABLE opening_position_records"))
    await db.execute(text("DROP INDEX uq_reconciliation_matches_active_atomic_txn"))
    await db.execute(
        text(
            "CREATE UNIQUE INDEX uq_reconciliation_matches_active_atomic_txn ON reconciliation_matches (atomic_txn_id) WHERE superseded_by_id IS NULL AND status <> 'superseded'::reconciliation_status_enum"
        )
    )
    path = Path(__file__).resolve().parents[2] / "migrations/versions/0060_opening_positions.py"
    spec = importlib.util.spec_from_file_location("opening_migration_under_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def upgrade(session):
        migration.op = Operations(MigrationContext.configure(session.connection()))
        migration.upgrade()

    await db.run_sync(upgrade)
    await db.commit()
    assert (
        await db.scalar(select(ReconciliationMatch.status).where(ReconciliationMatch.id == match_id))
        == ReconciliationStatus.REJECTED
    )
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={account_id: Decimal("100")},
        currency="SGD",
        base_currency="SGD",
    )
    await db.commit()
    with pytest.raises(DBAPIError, match="immutable"):
        async with db.begin_nested():
            await db.execute(text("UPDATE opening_position_records SET amount=101"))
    with pytest.raises(RuntimeError, match="verified pre-upgrade backup"):
        migration.downgrade()

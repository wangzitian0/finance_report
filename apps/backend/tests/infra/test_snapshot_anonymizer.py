"""#893 snapshot anonymizer — the data boundary of deploy(env, code, data).

AC-runtime.snapshot-anonymizer.1/2/3: fail-closed column classification,
balance-exact integer money scaling, deterministic pseudonyms plus a residual
scan that fails closed. RL-DATA-2: real data never leaves prod un-anonymized.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import Base
from src.extraction.orm.layer2 import AtomicPosition, AtomicTransaction, TransactionDirection
from src.ledger import JournalLine
from src.pricing import (
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
)
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.runtime.extension.snapshot_anonymizer import (
    Action,
    anonymize,
    classify_columns,
    scan_for_residuals,
)
from tests.ledger._ledger_helpers import create_valid_posted_entry

pytestmark = pytest.mark.asyncio

SECRET = "test-anonymizer-secret"
FACTOR = 3


def test_AC_runtime_snapshot_anonymizer_1_every_live_column_is_classified() -> None:
    """AC-runtime.snapshot-anonymizer.1: classify_columns covers the full live
    model metadata without raising — a migration adding an unclassified column
    turns this test red, so a snapshot can never silently carry it (RL-DATA-2,
    fail closed)."""
    plan = classify_columns(Base.metadata)
    # Spot-pin the four action families so a bulk misclassification is loud.
    assert plan["journal_lines.amount"] is Action.SCALE
    assert plan["journal_lines.fx_rate"] is Action.KEEP
    assert plan["users.email"] is Action.PSEUDONYM
    assert plan["users.hashed_password"] is Action.REDACT_SECRET
    assert plan["atomic_transactions.source_documents"] is Action.REDACT_JSON
    # Every column of every table is present in the plan.
    total_columns = sum(len(t.columns) for t in Base.metadata.sorted_tables)
    assert len(plan) == total_columns


def test_AC_runtime_snapshot_anonymizer_1_unknown_column_fails_closed() -> None:
    """AC-runtime.snapshot-anonymizer.1: an unclassified text column aborts
    before any data is read."""
    from src.runtime.extension.snapshot_anonymizer import UnclassifiedColumnError

    scratch = sa.MetaData()
    sa.Table("brand_new_table", scratch, sa.Column("free_text", sa.String(100)))
    with pytest.raises(UnclassifiedColumnError, match="brand_new_table.free_text"):
        classify_columns(scratch)


async def _seed(db: AsyncSession, test_user) -> dict:
    entry = await create_valid_posted_entry(db, test_user.id, memo="Salary from Acme Corp", amount=Decimal("2500.00"))
    txn = AtomicTransaction(
        user_id=test_user.id,
        txn_date=date(2026, 5, 2),
        amount=Decimal("2500.00"),
        currency="SGD",
        direction=TransactionDirection.IN,
        description="ACME CORP PAYROLL MAY",
        source_documents={"documents": [{"doc_id": "real-doc-1", "broker": "DBS Bank"}]},
        dedup_hash="real-dedup-hash-001",
    )
    position = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date(2026, 5, 31),
        asset_identifier="AAPL",
        broker="Moomoo Real Broker",
        quantity=Decimal("10"),
        market_value=Decimal("1800.00"),
        currency="SGD",
        dedup_hash="real-dedup-hash-002",
        source_documents={},
    )
    valuation = ManualValuationSnapshot(
        user_id=test_user.id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of_date=date(2026, 5, 1),
        value=Decimal("1200000.00"),
        currency="SGD",
        source="Sunny Vale Condo",
        notes="Bought from John Tan in 2020",
    )
    db.add_all([txn, position, valuation])
    await db.flush()
    return {"entry": entry, "txn": txn, "position": position, "valuation": valuation}


async def test_AC_runtime_snapshot_anonymizer_2_money_scales_and_books_still_balance(
    db: AsyncSession, test_user
) -> None:
    """AC-runtime.snapshot-anonymizer.2: every monetary value is multiplied by
    the same integer factor (exactly — no rounding), so double-entry balance
    holds after anonymization; quantities are untouched."""
    seeded = await _seed(db, test_user)
    entry_id = seeded["entry"].id
    position_id = seeded["position"].id

    connection = await db.connection()
    report = await connection.run_sync(lambda conn: anonymize(conn, Base.metadata, secret=SECRET, scale_factor=FACTOR))
    assert report.scale_factor == FACTOR
    db.expire_all()

    lines = (await db.execute(sa.select(JournalLine).where(JournalLine.journal_entry_id == entry_id))).scalars().all()
    amounts = sorted(line.amount for line in lines)
    assert amounts == [Decimal("7500.00"), Decimal("7500.00")]
    debits = sum(line.amount for line in lines if line.direction.value == "DEBIT")
    credits = sum(line.amount for line in lines if line.direction.value == "CREDIT")
    assert debits == credits

    position = await db.get(AtomicPosition, position_id)
    assert position.market_value == Decimal("5400.00")
    assert position.quantity == Decimal("10")  # quantities never scale


async def test_AC_runtime_snapshot_anonymizer_3_pseudonyms_consistent_and_no_residuals(
    db: AsyncSession, test_user
) -> None:
    """AC-runtime.snapshot-anonymizer.3: identity/content strings are replaced
    deterministically (same original → same pseudonym across columns), JSON is
    redacted, and the residual scan finds no original value; a planted residual
    is caught."""
    seeded = await _seed(db, test_user)
    txn_id = seeded["txn"].id
    valuation_id = seeded["valuation"].id
    user_id = test_user.id

    connection = await db.connection()
    report = await connection.run_sync(lambda conn: anonymize(conn, Base.metadata, secret=SECRET, scale_factor=FACTOR))
    db.expire_all()

    txn = await db.get(AtomicTransaction, txn_id)
    valuation = await db.get(ManualValuationSnapshot, valuation_id)
    assert txn.description != "ACME CORP PAYROLL MAY"
    assert txn.source_documents == {"anonymized": True}
    assert valuation.source != "Sunny Vale Condo"
    assert valuation.notes != "Bought from John Tan in 2020"
    assert "John Tan" not in (valuation.notes or "")

    refreshed_user = (
        await db.execute(sa.text("SELECT email, hashed_password FROM users WHERE id = :id").bindparams(id=user_id))
    ).one()
    assert refreshed_user.email.endswith("@anonymized.invalid")
    assert refreshed_user.hashed_password == "!anonymized"

    # Determinism: anonymizing the same original twice yields the same
    # pseudonym — cross-table join keys (broker == account name) stay aligned.
    from src.runtime.extension.snapshot_anonymizer import _pseudonym

    assert _pseudonym(SECRET, "Moomoo Real Broker", "generic") == _pseudonym(SECRET, "Moomoo Real Broker", "generic")

    residuals = await connection.run_sync(lambda conn: scan_for_residuals(conn, Base.metadata, report.original_values))
    assert residuals == []

    # Plant an original value back and prove the scan fails closed on it.
    await db.execute(
        sa.update(AtomicTransaction)
        .where(AtomicTransaction.id == txn_id)
        .values(description="wire from ACME CORP PAYROLL MAY again")
    )
    await db.flush()
    residuals = await connection.run_sync(lambda conn: scan_for_residuals(conn, Base.metadata, report.original_values))
    assert residuals == ["atomic_transactions.description"]


async def test_scale_factor_one_is_rejected(db: AsyncSession) -> None:
    """A factor of 1 would ship real amounts — refused outright."""
    connection = await db.connection()
    with pytest.raises(ValueError, match="scale_factor"):
        await connection.run_sync(lambda conn: anonymize(conn, Base.metadata, secret=SECRET, scale_factor=1))


async def test_entry_balance_invariant_property(db: AsyncSession, test_user) -> None:
    """Property form of AC-runtime.snapshot-anonymizer.2: for several entries of
    varying amounts, total debits equal total credits after anonymization."""
    user_id = test_user.id
    for cents, memo in ((Decimal("33.33"), "coffee"), (Decimal("1234.57"), "rent x")):
        await create_valid_posted_entry(db, user_id, memo=f"entry {memo}", amount=cents)
    connection = await db.connection()
    await connection.run_sync(lambda conn: anonymize(conn, Base.metadata, secret=SECRET, scale_factor=7))
    db.expire_all()
    rows = (
        await db.execute(
            sa.text(
                "SELECT direction, SUM(amount) FROM journal_lines jl "
                "JOIN journal_entries je ON jl.journal_entry_id = je.id "
                "WHERE je.user_id = :uid GROUP BY direction"
            ).bindparams(uid=user_id)
        )
    ).all()
    totals = {direction: total for direction, total in rows}
    assert totals.get("DEBIT") == totals.get("CREDIT") is not None

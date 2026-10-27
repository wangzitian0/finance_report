"""Balance-sheet provenance remains lineage metadata, never package authority."""

from datetime import date
from decimal import Decimal

import pytest

from src.audit import JournalEntrySourceType
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.reporting import generate_balance_sheet
from src.schemas.reporting import BalanceSheetResponse


async def _post(db, user_id, *, debit: Account, credit: Account, amount: Decimal, source_type) -> None:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2026, 1, 15),
        memo="balance-sheet provenance",
        source_type=source_type,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=debit.id,
                direction=Direction.DEBIT,
                amount=amount,
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=amount,
                currency="SGD",
            ),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_include_trust_signals_false_skips_provenance_scan(db, test_user):
    cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=test_user.id, name="Salary", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash, salary])
    await db.flush()
    await _post(
        db,
        test_user.id,
        debit=cash,
        credit=salary,
        amount=Decimal("100.00"),
        source_type=JournalEntrySourceType.MANUAL,
    )

    report = await generate_balance_sheet(
        db,
        test_user.id,
        as_of_date=date(2026, 12, 31),
        include_trust_signals=False,
    )

    assert all(line["provenance"] is None for line in report["assets"])


@pytest.mark.asyncio
async def test_balance_sheet_aggregate_provenance_is_populated(db, test_user):
    cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=test_user.id, name="Salary", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash, salary])
    await db.flush()
    await _post(
        db,
        test_user.id,
        debit=cash,
        credit=salary,
        amount=Decimal("100.00"),
        source_type=JournalEntrySourceType.AUTO_PARSED,
    )
    single = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 12, 31))
    assert single["provenance"] == "imported"

    wallet = Account(user_id=test_user.id, name="Wallet", type=AccountType.ASSET, currency="SGD")
    db.add(wallet)
    await db.flush()
    await _post(
        db,
        test_user.id,
        debit=wallet,
        credit=salary,
        amount=Decimal("50.00"),
        source_type=JournalEntrySourceType.MANUAL,
    )
    mixed = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 12, 31))
    assert mixed["provenance"] == "derived"


_ALLOCATION_METADATA_KEYS = {
    "allocation_asset_class",
    "allocation_liquidity_class",
    "allocation_source_type",
}


@pytest.mark.asyncio
async def test_balance_sheet_lines_carry_allocation_metadata_and_response_drops_it(db, test_user):
    """The service always emits allocation metadata; the response schema is the one place that removes it."""
    cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=test_user.id, name="Salary", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash, salary])
    await db.flush()
    await _post(
        db,
        test_user.id,
        debit=cash,
        credit=salary,
        amount=Decimal("100.00"),
        source_type=JournalEntrySourceType.MANUAL,
    )

    report = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 12, 31))

    assert report["assets"], "the seeded cash account must produce an asset line"
    assert all(_ALLOCATION_METADATA_KEYS <= set(line) for line in report["assets"])
    response_lines = BalanceSheetResponse.model_validate(report).model_dump()["assets"]
    assert response_lines
    assert all(not (_ALLOCATION_METADATA_KEYS & set(line)) for line in response_lines)

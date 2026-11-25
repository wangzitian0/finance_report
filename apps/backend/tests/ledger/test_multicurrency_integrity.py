from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import (
    AccountType,
    Direction,
    JournalEntryStatus,
    ValidationError,
    post_journal_entry,
    validate_journal_balance,
    verify_accounting_equation,
    void_journal_entry,
)
from tests.ledger._ledger_helpers import (
    create_anchored_test_journal_entry as create_journal_entry,
    make_account,
    make_entry,
    make_line,
)


def test_multicurrency_entry_balances_in_base_currency() -> None:
    bank_usd = make_line(Direction.DEBIT, "100.00", "USD", Decimal("1.350000"))
    equity_sgd = make_line(Direction.CREDIT, "135.00", "SGD")
    assert bank_usd.amount * bank_usd.fx_rate == equity_sgd.amount == Decimal("135.00")
    validate_journal_balance([bank_usd, equity_sgd])
    validate_journal_balance(
        [make_line(Direction.DEBIT, "100.00", None), make_line(Direction.CREDIT, "100.00", "USD")], base_currency="USD"
    )
    with pytest.raises(ValidationError):
        validate_journal_balance([bank_usd, make_line(Direction.CREDIT, "100.00", "SGD")])


async def test_accounting_equation_uses_base_currency_balances(db: AsyncSession, test_user) -> None:
    usd_asset = await make_account(db, test_user.id, "USD Bank", AccountType.ASSET, "USD")
    equity = await make_account(db, test_user.id, "Opening Equity", AccountType.EQUITY, "SGD")
    await make_entry(
        db,
        test_user.id,
        [
            (usd_asset.id, Direction.DEBIT, "100.00", "USD", Decimal("1.350000")),
            (equity.id, Direction.CREDIT, "135.00", "SGD"),
        ],
        entry_date=date(2026, 1, 1),
        memo="USD opening balance",
    )
    assert await verify_accounting_equation(db, test_user.id, base_currency="SGD") is True


async def test_effective_usd_base_and_historical_void_base(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    usd_asset = await make_account(db, uid, "USD Cash", AccountType.ASSET, "USD")
    usd_equity = await make_account(db, uid, "USD Equity", AccountType.EQUITY, "USD")
    usd_entry = await create_journal_entry(
        db,
        uid,
        date(2026, 1, 1),
        "USD base",
        [
            {"account_id": usd_asset.id, "direction": Direction.DEBIT, "amount": Decimal("100.00"), "currency": "USD"},
            {
                "account_id": usd_equity.id,
                "direction": Direction.CREDIT,
                "amount": Decimal("100.00"),
                "currency": "USD",
            },
        ],
        base_currency="USD",
    )
    await post_journal_entry(db, usd_entry.id, uid, base_currency="USD")
    await db.commit()
    with pytest.raises(ValidationError, match="fx_rate required"):
        await verify_accounting_equation(db, uid, base_currency="SGD")
    rev_usd = await void_journal_entry(db, usd_entry.id, "USD correction", uid, base_currency="USD")
    assert rev_usd.status == JournalEntryStatus.POSTED and {ln.currency for ln in rev_usd.lines} == {"USD"}
    assert await verify_accounting_equation(db, uid, base_currency="USD") is True

    sgd_asset = await make_account(db, uid, "Hist SGD Cash", AccountType.ASSET, "SGD")
    sgd_equity = await make_account(db, uid, "Hist SGD Equity", AccountType.EQUITY, "SGD")
    sgd_entry = await create_journal_entry(
        db,
        uid,
        date(2026, 1, 1),
        "Historical SGD",
        [
            {"account_id": sgd_asset.id, "direction": Direction.DEBIT, "amount": Decimal("100.00"), "currency": "SGD"},
            {
                "account_id": sgd_equity.id,
                "direction": Direction.CREDIT,
                "amount": Decimal("100.00"),
                "currency": "SGD",
            },
        ],
        base_currency="SGD",
    )
    await post_journal_entry(db, sgd_entry.id, uid, base_currency="SGD")
    await db.commit()
    rev_sgd = await void_journal_entry(db, sgd_entry.id, "Correction after base change", uid, base_currency="USD")
    assert {ln.currency for ln in rev_sgd.lines} == {"SGD"}


async def test_void_rejects_all_fx_entry_without_historical_basis(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    usd_asset = await make_account(db, uid, "All-FX USD", AccountType.ASSET, "USD")
    eur_equity = await make_account(db, uid, "All-FX EUR", AccountType.EQUITY, "EUR")
    entry = await create_journal_entry(
        db,
        uid,
        date(2026, 1, 1),
        "All-FX",
        [
            {
                "account_id": usd_asset.id,
                "direction": Direction.DEBIT,
                "amount": Decimal("100.00"),
                "currency": "USD",
                "fx_rate": Decimal("1.350000"),
            },
            {
                "account_id": eur_equity.id,
                "direction": Direction.CREDIT,
                "amount": Decimal("90.00"),
                "currency": "EUR",
                "fx_rate": Decimal("1.500000"),
            },
        ],
        base_currency="SGD",
    )
    await post_journal_entry(db, entry.id, uid, base_currency="SGD")
    await db.commit()
    with pytest.raises(ValidationError, match="Cannot determine historical base currency.*all lines have FX"):
        await void_journal_entry(db, entry.id, "Ambiguous historical basis", uid, base_currency="USD")

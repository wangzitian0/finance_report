from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.composition import compose_statement_posting_dependencies
from src.ledger import (
    AccountType,
    JournalEntry,
    ValidationError,
    initialize_opening_positions,
    list_opening_positions,
)
from src.ledger.extension.accounting import post_opening_balance_entry
from src.ledger.extension.anchored_posting import submit_system_journal_entry
from tests.factories import AccountFactory
from tests.ledger._ledger_helpers import make_account


@pytest.mark.parametrize("case", ["empty", "foreign", "system", "inactive", "numeric", "currency", "tiny_fx", "missing_emitter"])
async def test_opening_invalid_inputs_leave_no_stock(db, test_user, case: str) -> None:
    account = await make_account(
        db,
        test_user.id,
        "Guarded stock",
        AccountType.ASSET,
        "USD" if case == "tiny_fx" else "SGD",
        is_system=case == "system",
        is_active=case != "inactive",
    )
    balances = {} if case == "empty" else {uuid4() if case == "foreign" else account.id: 1 if case == "numeric" else Decimal("100")}
    kwargs = {"source_decision_id": uuid4()} if case == "missing_emitter" else {}
    with pytest.raises(ValidationError):
        await initialize_opening_positions(
            db,
            test_user.id,
            entry_date=date(2026, 1, 1),
            balances=balances,
            currency="USD" if case in {"currency", "tiny_fx"} else "SGD",
            base_currency="SGD",
            fx_rates={"USD": Decimal("0.00000001")},
            **kwargs,
        )
    assert await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == test_user.id)) == 0


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-100")])
async def test_legacy_opening_entry_rejects_nonpositive_and_foreign(db, test_user, amount: Decimal) -> None:
    account = await AccountFactory.create_async(db, user_id=test_user.id, currency="SGD")
    with pytest.raises(ValidationError, match="positive"):
        await post_opening_balance_entry(db, test_user.id, entry_date=date(2026, 1, 1), balances={account.id: amount}, currency="SGD", base_currency="SGD")
    with pytest.raises(ValidationError, match="base currency"):
        await post_opening_balance_entry(db, test_user.id, entry_date=date(2026, 1, 1), balances={uuid4(): Decimal("100")}, currency="USD", base_currency="SGD")
    assert await list_opening_positions(db, user_id=test_user.id, as_of=date.max) == ()
    assert await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == test_user.id)) == 0


async def test_historical_anchored_opening_is_not_recreated(db, test_user) -> None:
    asset = await make_account(db, test_user.id, "Legacy bank", AccountType.ASSET)
    equity = await make_account(db, test_user.id, "Legacy equity", AccountType.EQUITY, is_system=True)
    entry = await submit_system_journal_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2026, 1, 1),
        memo="Legacy opening",
        operation="opening-balance",
        base_currency="SGD",
        lines_data=[
            {"account_id": asset.id, "direction": "DEBIT", "amount": Decimal("100"), "currency": "SGD"},
            {"account_id": equity.id, "direction": "CREDIT", "amount": Decimal("100"), "currency": "SGD"},
        ],
    )
    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date(2026, 1, 31))
    assert len(positions) == 1 and (positions[0].account_id, positions[0].amount, positions[0].journal_entry_id, positions[0].state) == (
        asset.id,
        Decimal("100"),
        entry.id,
        "authoritative",
    )
    again = await initialize_opening_positions(db, test_user.id, entry_date=date(2026, 1, 1), balances={asset.id: Decimal("100")}, currency="SGD", base_currency="SGD")
    assert again.id == entry.id


@pytest.mark.parametrize("case", ["unknown_source", "prior_activity", "changed_stock"])
async def test_opening_rejects_missing_authority_or_historical_rewrite(db, test_user, case: str) -> None:
    asset = await make_account(db, test_user.id, "Guarded bank", AccountType.ASSET)
    equity = await make_account(db, test_user.id, "Guarded equity", AccountType.EQUITY, is_system=True)
    if case != "unknown_source":
        await submit_system_journal_entry(
            db,
            user_id=test_user.id,
            entry_date=date(2025, 12, 31),
            memo="Previous activity",
            operation="opening-balance" if case == "changed_stock" else "historical-activity",
            base_currency="SGD",
            lines_data=[
                {"account_id": asset.id, "direction": "DEBIT", "amount": Decimal("100"), "currency": "SGD"},
                {"account_id": equity.id, "direction": "CREDIT", "amount": Decimal("100"), "currency": "SGD"},
            ],
        )
    kwargs = {"source_decision_id": uuid4(), "trace_emitter": compose_statement_posting_dependencies().trace_emitter_factory(db)} if case == "unknown_source" else {}
    with pytest.raises(ValidationError):
        await initialize_opening_positions(db, test_user.id, entry_date=date(2026, 1, 1), balances={asset.id: Decimal("200")}, currency="SGD", base_currency="SGD", **kwargs)
    assert await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == test_user.id)) == (0 if case == "unknown_source" else 1)

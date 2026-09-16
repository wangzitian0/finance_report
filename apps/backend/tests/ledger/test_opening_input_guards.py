"""Persisted opening input failures cannot create stock or journal authority."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.ledger import Account, AccountType, JournalEntry, ValidationError, initialize_opening_positions
from src.ledger.extension.accounting import post_opening_balance_entry


@pytest.mark.parametrize(
    "case", ["empty", "foreign", "system", "inactive", "numeric", "currency", "tiny_fx", "missing_emitter"]
)
async def test_opening_invalid_inputs_leave_no_stock(db, test_user, case):
    """AC-ledger.opening-position.4: rejected input never becomes starting stock."""
    account = Account(
        user_id=test_user.id,
        name="Guarded stock",
        type=AccountType.ASSET,
        currency="USD" if case == "tiny_fx" else "SGD",
        is_system=case == "system",
        is_active=case != "inactive",
    )
    db.add(account)
    await db.flush()
    balances = (
        {}
        if case == "empty"
        else {uuid4() if case == "foreign" else account.id: 1 if case == "numeric" else Decimal("100")}
    )
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
    assert (
        await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == test_user.id)) == 0
    )


async def test_legacy_opening_rejects_foreign_currency(db, test_user):
    """AC-ledger.opening-position.4: legacy API cannot silently reinterpret foreign stock."""
    with pytest.raises(ValidationError, match="base currency"):
        await post_opening_balance_entry(
            db,
            test_user.id,
            entry_date=date(2026, 1, 1),
            balances={uuid4(): Decimal("100")},
            currency="USD",
            base_currency="SGD",
        )


async def test_historical_anchored_opening_is_not_recreated(db, test_user):
    """AC-ledger.opening-position.2: pre-position anchored stock remains authoritative and idempotent."""
    from src.ledger import list_opening_positions
    from src.ledger.extension.anchored_posting import submit_system_journal_entry

    asset = Account(user_id=test_user.id, name="Legacy bank", type=AccountType.ASSET, currency="SGD")
    equity = Account(
        user_id=test_user.id, name="Legacy equity", type=AccountType.EQUITY, currency="SGD", is_system=True
    )
    db.add_all([asset, equity])
    await db.flush()
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
    assert len(positions) == 1
    assert positions[0].account_id == asset.id and positions[0].amount == Decimal("100")
    assert positions[0].journal_entry_id == entry.id
    assert positions[0].state == "authoritative"
    again = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={asset.id: Decimal("100")},
        currency="SGD",
        base_currency="SGD",
    )
    assert again.id == entry.id


@pytest.mark.parametrize("case", ["unknown_source", "prior_activity", "changed_stock"])
async def test_opening_rejects_missing_authority_or_historical_rewrite(db, test_user, case):
    """AC-ledger.opening-position.2: a retry cannot rewrite existing history or invent authority."""
    from src.composition import compose_statement_posting_dependencies
    from src.ledger.extension.anchored_posting import submit_system_journal_entry

    asset = Account(user_id=test_user.id, name="Guarded historical bank", type=AccountType.ASSET, currency="SGD")
    equity = Account(
        user_id=test_user.id, name="Guarded historical equity", type=AccountType.EQUITY, currency="SGD", is_system=True
    )
    db.add_all([asset, equity])
    await db.flush()
    if case != "unknown_source":
        await submit_system_journal_entry(
            db,
            user_id=test_user.id,
            entry_date=date(2025, 12, 31),
            memo="Previous immutable activity",
            operation="opening-balance" if case == "changed_stock" else "historical-activity",
            base_currency="SGD",
            lines_data=[
                {"account_id": asset.id, "direction": "DEBIT", "amount": Decimal("100"), "currency": "SGD"},
                {"account_id": equity.id, "direction": "CREDIT", "amount": Decimal("100"), "currency": "SGD"},
            ],
        )
    kwargs = (
        {
            "source_decision_id": uuid4(),
            "trace_emitter": compose_statement_posting_dependencies().trace_emitter_factory(db),
        }
        if case == "unknown_source"
        else {}
    )
    with pytest.raises(ValidationError):
        await initialize_opening_positions(
            db,
            test_user.id,
            entry_date=date(2026, 1, 1),
            balances={asset.id: Decimal("200")},
            currency="SGD",
            base_currency="SGD",
            **kwargs,
        )
    assert await db.scalar(
        select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == test_user.id)
    ) == (0 if case == "unknown_source" else 1)

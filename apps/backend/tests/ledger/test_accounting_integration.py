from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.config import settings
from src.ledger import (
    Account,
    AccountType,
    DecisionAnchorError,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    ValidationError,
    calculate_account_balance,
    calculate_account_balances,
    post_journal_entry,
    validate_fx_rates,
    validate_journal_balance,
    validate_journal_posting_invariants,
    validate_line_account_ownership,
    verify_accounting_equation,
    void_journal_entry,
)
from tests.factories import UserFactory
from tests.ledger._ledger_helpers import (
    create_anchored_test_journal_entry as create_journal_entry,
    create_valid_posted_entry,
    lines_pair,
    make_account,
    make_entry,
    make_line,
)


async def test_balances_and_accounting_equation_across_account_types(db: AsyncSession, test_user_id) -> None:
    asset, liability, equity, income, expense, empty = [
        await make_account(db, test_user_id, name, atype)
        for name, atype in (
            ("Bank", AccountType.ASSET),
            ("Card", AccountType.LIABILITY),
            ("Equity", AccountType.EQUITY),
            ("Salary", AccountType.INCOME),
            ("Food", AccountType.EXPENSE),
            ("Empty", AccountType.LIABILITY),
        )
    ]
    await make_entry(
        db,
        test_user_id,
        [
            (asset.id, Direction.DEBIT, "1000"),
            (expense.id, Direction.DEBIT, "100"),
            (liability.id, Direction.CREDIT, "200"),
            (equity.id, Direction.CREDIT, "300"),
            (income.id, Direction.CREDIT, "600"),
        ],
    )
    await make_entry(
        db, test_user_id, [(asset.id, Direction.DEBIT, "9999"), (income.id, Direction.CREDIT, "9999")], status=JournalEntryStatus.DRAFT
    )
    await db.commit()

    assert await calculate_account_balance(db, asset.id, test_user_id) == Decimal("1000.00")
    assert await calculate_account_balance(db, income.id, test_user_id) == Decimal("600.00")
    assert await calculate_account_balance(db, empty.id, test_user_id) == Decimal("0")
    balances = await calculate_account_balances(db, [asset, liability, equity, income, expense], test_user_id)
    assert (balances[asset.id], balances[liability.id], balances[equity.id], balances[income.id], balances[expense.id]) == (
        Decimal("1000.00"),
        Decimal("200.00"),
        Decimal("300.00"),
        Decimal("600.00"),
        Decimal("100.00"),
    )
    assert await calculate_account_balances(db, [], test_user_id) == {}
    assert await verify_accounting_equation(db, test_user_id, base_currency="SGD") is True


async def test_cross_user_isolation_and_db_boundary(db: AsyncSession, test_user_id) -> None:
    salary = await make_account(db, test_user_id, "Salary", AccountType.INCOME)
    other_id = (await UserFactory.create_async(db)).id
    other_acc = await make_account(db, other_id, "Other Cash", AccountType.ASSET, commit=True)

    assert await validate_line_account_ownership(db, test_user_id, set()) == {}
    missing_id = uuid4()
    with pytest.raises(ValidationError, match=f"Account {missing_id} not found"):
        await validate_line_account_ownership(db, test_user_id, {missing_id})
    with pytest.raises(ValidationError, match="Account does not belong to user"):
        await create_journal_entry(db, test_user_id, date.today(), "Cross", lines_pair(other_acc.id, salary.id, "10.00"))
    with pytest.raises(IntegrityError, match="cannot reference cross-user account"):
        await make_entry(db, test_user_id, [(other_acc.id, Direction.DEBIT, "25"), (salary.id, Direction.CREDIT, "25")], status=JournalEntryStatus.DRAFT)
    await db.rollback()

    other_acc = await make_account(db, other_id, "Other Cash 2", AccountType.ASSET)
    salary = await make_account(db, test_user_id, "Salary 2", AccountType.INCOME)
    polluted = JournalEntry(
        user_id=test_user_id, entry_date=date.today(), memo="Pollution", source_type=JournalEntrySourceType.MANUAL, status=JournalEntryStatus.POSTED
    )
    db.add(polluted)
    await db.flush()
    try:
        await db.execute(text("SET LOCAL session_replication_role = replica"))
        db.add_all(
            [
                JournalLine(journal_entry_id=polluted.id, account_id=other_acc.id, direction=Direction.DEBIT, amount=Decimal("99.00"), currency="SGD"),
                JournalLine(journal_entry_id=polluted.id, account_id=salary.id, direction=Direction.CREDIT, amount=Decimal("99.00"), currency="SGD"),
            ]
        )
        await db.flush()
    finally:
        await db.execute(text("SET LOCAL session_replication_role = DEFAULT"))
    await db.commit()
    assert (await calculate_account_balances(db, [other_acc], other_id))[other_acc.id] == Decimal("0")

    unloaded = JournalEntry(user_id=test_user_id, entry_date=date.today(), memo="Missing", source_type=JournalEntrySourceType.MANUAL, status=JournalEntryStatus.DRAFT)
    unloaded.lines = [make_line(Direction.DEBIT, "25.00"), make_line(Direction.CREDIT, "25.00")]
    with pytest.raises(ValidationError, match="not found"):
        validate_journal_posting_invariants(unloaded)


async def test_create_journal_entry_options_and_flush(db: AsyncSession, test_user_id, monkeypatch: pytest.MonkeyPatch) -> None:
    bank = await make_account(db, test_user_id, "Bank", AccountType.ASSET)
    salary = await make_account(db, test_user_id, "Salary", AccountType.INCOME)

    source_id = uuid4()
    custom = await create_journal_entry(
        db, test_user_id, date.today(), "Bank stmt", lines_pair(bank.id, salary.id, "200.00"), source_type="bank_statement", source_id=source_id
    )
    assert custom.source_type == JournalEntrySourceType.AUTO_PARSED and custom.source_id == source_id

    tagged = await create_journal_entry(
        db,
        test_user_id,
        date.today(),
        "USD/Tagged",
        [
            {"account_id": bank.id, "direction": Direction.DEBIT, "amount": Decimal("100.00"), "currency": "USD", "fx_rate": Decimal("1.35"), "event_type": "DEPOSIT", "tags": {"labels": ["salary"]}},
            {"account_id": salary.id, "direction": Direction.CREDIT, "amount": Decimal("135.00")},
        ],
    )
    usd_line = next(ln for ln in tagged.lines if ln.currency == "USD")
    assert (usd_line.fx_rate, usd_line.event_type, usd_line.tags) == (Decimal("1.35"), "DEPOSIT", {"labels": ["salary"]})
    await db.commit()

    monkeypatch.setattr(settings, "base_currency", "usd")
    usd_default = await create_journal_entry(
        db, test_user_id, date.today(), "Configured USD", [{"account_id": bank.id, "direction": Direction.DEBIT, "amount": Decimal("50")}, {"account_id": salary.id, "direction": Direction.CREDIT, "amount": Decimal("50")}]
    )
    assert {ln.currency for ln in usd_default.lines} == {"USD"}
    await db.rollback()
    assert (await db.execute(select(JournalEntry).where(JournalEntry.id == usd_default.id))).scalar_one_or_none() is None


async def test_post_and_void_lifecycle_and_errors(db: AsyncSession, test_user_id) -> None:
    bank = await make_account(db, test_user_id, "Bank", AccountType.ASSET)
    salary = await make_account(db, test_user_id, "Salary", AccountType.INCOME)
    inactive = await make_account(db, test_user_id, "Inactive", AccountType.ASSET, is_active=False)

    draft = await create_journal_entry(db, test_user_id, date.today(), "Draft", lines_pair(bank.id, salary.id, "1000.00"))
    posted = await post_journal_entry(db, draft.id, test_user_id)
    assert posted.status == JournalEntryStatus.POSTED
    with pytest.raises(ValidationError, match="Can only post draft entries"):
        await post_journal_entry(db, posted.id, test_user_id)

    reversal = await void_journal_entry(db, posted.id, "Test void", test_user_id)
    await db.refresh(posted)
    rev_map = {ln.account_id: ln for ln in reversal.lines}
    assert (posted.status, posted.void_reason, posted.void_reversal_entry_id) == (JournalEntryStatus.VOID, "Test void", reversal.id)
    assert "VOID" in reversal.memo and rev_map[bank.id].direction == Direction.CREDIT and rev_map[salary.id].direction == Direction.DEBIT

    other_id = (await UserFactory.create_async(db)).id
    other_acc = await make_account(db, other_id, "O", AccountType.ASSET, commit=True)
    other_posted = await create_valid_posted_entry(db, other_id, memo="Other posted")
    other_draft = await make_entry(db, other_id, [], status=JournalEntryStatus.DRAFT, commit=True)
    inactive_draft = await make_entry(db, test_user_id, [(inactive.id, Direction.DEBIT, "100"), (salary.id, Direction.CREDIT, "100")], status=JournalEntryStatus.DRAFT, commit=True)
    unbalanced_draft = await make_entry(db, test_user_id, [(bank.id, Direction.DEBIT, "100"), (salary.id, Direction.CREDIT, "90")], status=JournalEntryStatus.DRAFT, commit=True)
    single_draft = await make_entry(db, test_user_id, [(bank.id, Direction.DEBIT, "100")], status=JournalEntryStatus.DRAFT, commit=True)
    unanchored_draft = await make_entry(db, test_user_id, [(bank.id, Direction.DEBIT, "100"), (salary.id, Direction.CREDIT, "100")], status=JournalEntryStatus.DRAFT, commit=True)

    for err_cls, match, fn in (
        (ValidationError, "not found", lambda: calculate_account_balance(db, uuid4(), test_user_id)),
        (ValidationError, "does not belong to user", lambda: calculate_account_balance(db, other_acc.id, test_user_id)),
        (ValidationError, "not found", lambda: post_journal_entry(db, uuid4(), test_user_id)),
        (ValidationError, "does not belong to user", lambda: post_journal_entry(db, other_draft.id, test_user_id)),
        (ValidationError, "is not active", lambda: post_journal_entry(db, inactive_draft.id, test_user_id)),
        (ValidationError, "not balanced", lambda: post_journal_entry(db, unbalanced_draft.id, test_user_id)),
        (ValidationError, "at least 2 lines", lambda: post_journal_entry(db, single_draft.id, test_user_id)),
        (DecisionAnchorError, "legacy-unproven journal entries cannot be posted", lambda: post_journal_entry(db, unanchored_draft.id, test_user_id)),
        (ValidationError, "not found", lambda: void_journal_entry(db, uuid4(), "r", test_user_id)),
        (ValidationError, "does not belong to user", lambda: void_journal_entry(db, other_posted.id, "r", test_user_id)),
        (ValidationError, "Can only void posted entries", lambda: void_journal_entry(db, unanchored_draft.id, "r", test_user_id)),
        (ValidationError, "Journal entry not balanced", lambda: create_journal_entry(db, test_user_id, date.today(), "Unbal", lines_pair(bank.id, salary.id)[:-1] + [{"account_id": salary.id, "direction": Direction.CREDIT, "amount": Decimal("90")}])),
        (ValidationError, "fx_rate required for currency USD", lambda: create_journal_entry(db, test_user_id, date.today(), "FX", [{"account_id": bank.id, "direction": Direction.DEBIT, "amount": Decimal("100"), "currency": "USD"}, {"account_id": salary.id, "direction": Direction.CREDIT, "amount": Decimal("135")}])),
    ):
        with pytest.raises(err_cls, match=match):
            await fn()

    with pytest.raises(ValidationError, match="amount must be positive"):
        validate_journal_balance([make_line(Direction.DEBIT, "100"), make_line(Direction.CREDIT, "100"), make_line(Direction.DEBIT, "0")])
    with pytest.raises(ValidationError, match="fx_rate required"):
        validate_fx_rates([JournalLine(currency="USD", fx_rate=None)])

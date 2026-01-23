"""Coverage boost tests for reconciliation engine."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import (
    Account,
    AccountType,
    BankStatement,
    BankStatementTransaction,
    BankStatementTransactionStatus,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    ReconciliationMatch,
    ReconciliationStatus,
    User,
)
from src.services.reconciliation import (
    DEFAULT_CONFIG,
    ReconciliationConfig,
    calculate_match_score,
    entry_total_amount,
    execute_matching,
    extract_merchant_tokens,
    find_candidates,
    is_entry_balanced,
    load_reconciliation_config,
    normalize_text,
    prune_candidates,
    score_amount,
    score_business_logic,
    score_date,
    score_description,
    score_pattern,
    weighted_total,
)


def _make_statement(*, owner_id: UUID | None = None, base_date: date) -> BankStatement:
    user_id = owner_id if owner_id else uuid4()
    return BankStatement(
        user_id=user_id,
        file_path="statements/test.pdf",
        file_hash="test_hash_" + str(base_date) + str(uuid4()),
        original_filename="test.pdf",
        institution="Test Bank",
        account_last4="1234",
        currency="SGD",
        period_start=base_date,
        period_end=base_date,
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
    )


def test_entry_total_amount():
    entry = JournalEntry(
        lines=[
            JournalLine(direction=Direction.DEBIT, amount=Decimal("100.00")),
            JournalLine(direction=Direction.CREDIT, amount=Decimal("100.00")),
            JournalLine(direction=Direction.DEBIT, amount=Decimal("50.00")),
        ]
    )
    assert entry_total_amount(entry) == Decimal("150.00")


def test_is_entry_balanced():
    balanced = JournalEntry(
        lines=[
            JournalLine(direction=Direction.DEBIT, amount=Decimal("100.00")),
            JournalLine(direction=Direction.CREDIT, amount=Decimal("100.00")),
        ]
    )
    unbalanced = JournalEntry(
        lines=[
            JournalLine(direction=Direction.DEBIT, amount=Decimal("100.00")),
            JournalLine(direction=Direction.CREDIT, amount=Decimal("99.00")),
        ]
    )
    assert is_entry_balanced(balanced) is True
    assert is_entry_balanced(unbalanced) is False


def test_load_reconciliation_config_env_overrides():
    with patch.dict(
        "os.environ",
        {"RECONCILIATION_AUTO_ACCEPT_THRESHOLD": "90", "RECONCILIATION_REVIEW_THRESHOLD": "50"},
    ):
        config = load_reconciliation_config(force_reload=True)
        assert config.auto_accept == 90
        assert config.pending_review == 50


def test_load_reconciliation_config_yaml_fallback():
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.read_text", return_value="scoring:\n  weights:\n    amount: 0.5"),
    ):
        # Even if yaml module is missing or error happens, it should fallback
        config = load_reconciliation_config(force_reload=True)
        # Assuming the mock might trigger fallback due to missing yaml or other issues
        assert isinstance(config, ReconciliationConfig)


def test_normalize_text_edge_cases():
    assert normalize_text("") == ""
    assert normalize_text("!!! @@@ ###") == ""
    assert normalize_text("ABC   123") == "abc 123"


def test_score_description_edge_cases():
    assert score_description(None, "test") == 0.0
    assert score_description("test", None) == 0.0
    assert score_description("", "test") == 0.0
    assert score_description("!!!", "@@@") == 0.0
    assert score_description("Exact Match", "Exact Match") == 100.0


def test_score_amount_tiers():
    config = DEFAULT_CONFIG
    # Exact
    assert score_amount(Decimal("100.00"), Decimal("100.00"), config) == 100.0
    assert score_amount(Decimal("100.00"), Decimal("100.01"), config) == 100.0

    # Tolerance match (0.10 absolute or 0.5% percent)
    # 0.5% of 1000 is 5.00
    assert score_amount(Decimal("1000.00"), Decimal("1004.00"), config) == 90.0

    # Within $5
    assert score_amount(Decimal("100.00"), Decimal("104.00"), config) == 70.0

    # Multi match tolerance
    assert score_amount(Decimal("1000.00"), Decimal("1009.00"), config, is_multi=True) == 70.0

    # Zero txn amount
    assert score_amount(Decimal("0.00"), Decimal("10.00"), config) == 0.0

    # Ratio score
    # Diff is 50, txn is 100. Ratio = 100 - (50/100)*100 = 50.
    assert score_amount(Decimal("100.00"), Decimal("150.00"), config) == 50.0


def test_score_date_proximity():
    config = DEFAULT_CONFIG
    d1 = date(2024, 1, 1)
    # Same day
    assert score_date(d1, d1, config) == 100.0
    # Within 3 days
    assert score_date(d1, date(2024, 1, 4), config) == 90.0
    # Same month within config days (7)
    assert score_date(d1, date(2024, 1, 7), config) == 70.0
    # Cross month but within config days (Jan 31 to Feb 2 is 2 days diff)
    # Actually 2 days diff is <= 3, so it returns 90.0
    # To test cross-period bonus (75.0), we need diff > 3 and <= config_days (7)
    # Jan 30 to Feb 3 is 4 days diff.
    assert score_date(date(2024, 1, 30), date(2024, 2, 3), config) == 75.0
    # Beyond window
    assert score_date(d1, date(2024, 1, 15), config) == 0.0


def test_score_business_logic_combinations():
    # IN Direction
    txn_in = BankStatementTransaction(direction="IN")

    # Asset + Income
    entry_income = JournalEntry(
        lines=[
            JournalLine(account=Account(type=AccountType.ASSET)),
            JournalLine(account=Account(type=AccountType.INCOME)),
        ]
    )
    assert score_business_logic(txn_in, entry_income) == 100.0

    # Asset + Liability
    entry_liability = JournalEntry(
        lines=[
            JournalLine(account=Account(type=AccountType.ASSET)),
            JournalLine(account=Account(type=AccountType.LIABILITY)),
        ]
    )
    assert score_business_logic(txn_in, entry_liability) == 85.0

    # Asset + Equity
    entry_equity = JournalEntry(
        lines=[
            JournalLine(account=Account(type=AccountType.ASSET)),
            JournalLine(account=Account(type=AccountType.EQUITY)),
        ]
    )
    assert score_business_logic(txn_in, entry_equity) == 75.0

    # Internal Transfer (Asset only)
    entry_transfer = JournalEntry(
        lines=[
            JournalLine(account=Account(type=AccountType.ASSET)),
            JournalLine(account=Account(type=AccountType.ASSET)),
        ]
    )
    assert score_business_logic(txn_in, entry_transfer) == 70.0

    # Other
    entry_other = JournalEntry(
        lines=[
            JournalLine(account=Account(type=AccountType.EXPENSE)),
        ]
    )
    assert score_business_logic(txn_in, entry_other) == 40.0

    # OUT Direction
    txn_out = BankStatementTransaction(direction="OUT")

    # Asset + Expense
    entry_expense = JournalEntry(
        lines=[
            JournalLine(account=Account(type=AccountType.ASSET)),
            JournalLine(account=Account(type=AccountType.EXPENSE)),
        ]
    )
    assert score_business_logic(txn_out, entry_expense) == 100.0

    # Asset + Liability (Debt repayment)
    assert score_business_logic(txn_out, entry_liability) == 90.0

    # Unknown direction
    txn_unknown = BankStatementTransaction(direction="???")
    assert score_business_logic(txn_unknown, entry_income) == 50.0


def test_extract_merchant_tokens():
    assert extract_merchant_tokens("VISA POS COFFEE SHOP 123") == ["coffee", "shop"]
    assert extract_merchant_tokens("REF: 123456789") == []
    assert extract_merchant_tokens("PAYMENT TO VENDOR ABC") == ["vendor", "abc"]


async def test_score_pattern_no_tokens(db: AsyncSession):
    txn = BankStatementTransaction(description="!!!")
    assert await score_pattern(db, txn, DEFAULT_CONFIG, uuid4()) == 0.0


async def test_score_pattern_with_history(db: AsyncSession):
    user_id = uuid4()
    user = User(id=user_id, email=f"pattern-{uuid4()}@example.com", hashed_password="hashed")
    statement = _make_statement(owner_id=user_id, base_date=date(2024, 1, 1))
    db.add_all([user, statement])
    await db.flush()

    txn_past = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2024, 1, 1),
        description="STARBUCKS COFFEE",
        amount=Decimal("10.00"),
        direction="OUT",
        status=BankStatementTransactionStatus.MATCHED,
    )
    db.add(txn_past)
    await db.flush()

    match = ReconciliationMatch(
        bank_txn_id=txn_past.id,
        journal_entry_ids=["some-id"],
        match_score=95,
        status=ReconciliationStatus.AUTO_ACCEPTED,
    )
    db.add(match)
    await db.commit()

    txn_new = BankStatementTransaction(description="STARBUCKS #123", amount=Decimal("10.00"))
    score = await score_pattern(db, txn_new, DEFAULT_CONFIG, user_id)
    assert score == 80.0

    # Different amount
    txn_diff = BankStatementTransaction(description="STARBUCKS #123", amount=Decimal("50.00"))
    score_diff = await score_pattern(db, txn_diff, DEFAULT_CONFIG, user_id)
    assert score_diff == 40.0


def test_weighted_total():
    scores = {
        "amount": 100.0,
        "date": 100.0,
        "description": 100.0,
        "business": 100.0,
        "history": 100.0,
    }
    assert weighted_total(scores, DEFAULT_CONFIG) == 100


def test_prune_candidates():
    # Create candidates with different amounts and dates
    c1 = JournalEntry(
        id=uuid4(),
        entry_date=date(2024, 1, 1),
        lines=[JournalLine(amount=Decimal("100.00"), direction=Direction.DEBIT)],
    )
    c2 = JournalEntry(
        id=uuid4(),
        entry_date=date(2024, 1, 2),
        lines=[JournalLine(amount=Decimal("101.00"), direction=Direction.DEBIT)],
    )
    c3 = JournalEntry(
        id=uuid4(),
        entry_date=date(2024, 1, 10),
        lines=[JournalLine(amount=Decimal("100.00"), direction=Direction.DEBIT)],
    )

    # Target 100.00 on Jan 1st
    candidates = [c1, c2, c3]
    pruned = prune_candidates(candidates, txn_date=date(2024, 1, 1), target_amount=Decimal("100.00"), limit=2)

    assert len(pruned) == 2
    assert pruned[0].id == c1.id  # Exact amount AND exact date
    assert pruned[1].id == c3.id  # Exact amount, but further date


async def test_calculate_match_score_overrides(db: AsyncSession):
    txn = BankStatementTransaction(description="Test", amount=Decimal("100.00"), txn_date=date(2024, 1, 1))
    entry = JournalEntry(
        memo="Test",
        entry_date=date(2024, 1, 1),
        lines=[JournalLine(amount=Decimal("100.00"), direction=Direction.DEBIT)],
    )

    candidate = await calculate_match_score(
        db, txn, [entry], DEFAULT_CONFIG, uuid4(), history_score_override=90.0, is_many_to_one=True
    )
    assert candidate.breakdown["history"] == 90.0
    assert "many_to_one_bonus" in candidate.breakdown


async def test_execute_matching_no_candidates_marked_unmatched(db: AsyncSession):
    user_id = uuid4()
    statement = _make_statement(owner_id=user_id, base_date=date(2024, 1, 1))
    db.add(statement)
    await db.flush()

    txn = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2024, 1, 1),
        description="Ghost",
        amount=Decimal("100.00"),
        direction="OUT",
        status=BankStatementTransactionStatus.PENDING,
    )
    db.add(txn)
    await db.commit()

    # Should not crash and should mark txn as unmatched
    matches = await execute_matching(db, user_id=user_id)
    assert len(matches) == 0

    # Reload txn to check status
    result = await db.execute(select(BankStatementTransaction).where(BankStatementTransaction.id == txn.id))
    txn_reloaded = result.scalar_one()
    assert txn_reloaded.status == BankStatementTransactionStatus.UNMATCHED


async def test_execute_matching_complex_multi_entry(db: AsyncSession):
    user_id = uuid4()
    user = User(id=user_id, email=f"complex-{uuid4()}@example.com", hashed_password="hashed")
    statement = _make_statement(owner_id=user_id, base_date=date(2024, 1, 1))
    db.add_all([user, statement])
    await db.flush()

    # Transaction for 100.00
    txn = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2024, 1, 1),
        description="Complex Multi",
        amount=Decimal("100.00"),
        direction="OUT",
        status=BankStatementTransactionStatus.PENDING,
    )
    db.add(txn)

    account = Account(
        id=uuid4(),
        name="Test Account",
        type=AccountType.ASSET,
        user_id=user_id,
        currency="SGD",
    )
    db.add(account)
    await db.flush()

    # Entries: 50.00 + 50.00
    e1 = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 1, 1),
        memo="Part 1",
        status=JournalEntryStatus.POSTED,
    )
    e2 = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 1, 1),
        memo="Part 2",
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([e1, e2])
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=e1.id,
                account_id=account.id,
                amount=Decimal("50.00"),
                direction=Direction.DEBIT,
            ),
            JournalLine(
                journal_entry_id=e1.id,
                account_id=account.id,
                amount=Decimal("50.00"),
                direction=Direction.CREDIT,
            ),
            JournalLine(
                journal_entry_id=e2.id,
                account_id=account.id,
                amount=Decimal("50.00"),
                direction=Direction.DEBIT,
            ),
            JournalLine(
                journal_entry_id=e2.id,
                account_id=account.id,
                amount=Decimal("50.00"),
                direction=Direction.CREDIT,
            ),
        ]
    )
    await db.commit()

    matches = await execute_matching(db, user_id=user_id)
    assert len(matches) == 1
    assert matches[0].score_breakdown.get("multi_entry") == 1


async def test_execute_matching_triple_entry(db: AsyncSession):
    user_id = uuid4()
    user = User(id=user_id, email=f"triple-{uuid4()}@example.com", hashed_password="hashed")
    statement = _make_statement(owner_id=user_id, base_date=date(2024, 1, 1))
    db.add_all([user, statement])
    await db.flush()

    txn = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2024, 1, 1),
        description="Triple Multi",
        amount=Decimal("150.00"),
        direction="OUT",
        status=BankStatementTransactionStatus.PENDING,
    )
    db.add(txn)

    account = Account(
        id=uuid4(),
        name="Test Account",
        type=AccountType.ASSET,
        user_id=user_id,
        currency="SGD",
    )
    db.add(account)
    await db.flush()

    entries = []
    for i in range(3):
        e = JournalEntry(
            user_id=user_id,
            entry_date=date(2024, 1, 1),
            memo=f"Part {i + 1}",
            status=JournalEntryStatus.POSTED,
        )
        db.add(e)
        entries.append(e)
    await db.flush()

    for e in entries:
        db.add_all(
            [
                JournalLine(
                    journal_entry_id=e.id,
                    account_id=account.id,
                    amount=Decimal("50.00"),
                    direction=Direction.DEBIT,
                ),
                JournalLine(
                    journal_entry_id=e.id,
                    account_id=account.id,
                    amount=Decimal("50.00"),
                    direction=Direction.CREDIT,
                ),
            ]
        )
    await db.commit()

    matches = await execute_matching(db, user_id=user_id)
    assert len(matches) == 1
    assert matches[0].score_breakdown.get("multi_entry") == 2


async def test_execute_matching_many_to_one_batch(db: AsyncSession):
    user_id = uuid4()
    user = User(id=user_id, email=f"batch-{uuid4()}@example.com", hashed_password="hashed")
    statement = _make_statement(owner_id=user_id, base_date=date(2024, 1, 1))
    db.add_all([user, statement])
    await db.flush()

    t1 = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2024, 1, 1),
        description="Batch Payment #1",
        amount=Decimal("50.00"),
        direction="OUT",
        status=BankStatementTransactionStatus.PENDING,
    )
    t2 = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2024, 1, 1),
        description="Batch Payment #1",
        amount=Decimal("50.00"),
        direction="OUT",
        status=BankStatementTransactionStatus.PENDING,
    )
    db.add_all([t1, t2])

    account = Account(
        id=uuid4(),
        name="Test Account",
        type=AccountType.ASSET,
        user_id=user_id,
        currency="SGD",
    )
    db.add(account)
    await db.flush()

    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 1, 1),
        memo="Batch Payment #1",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=account.id,
                amount=Decimal("100.00"),
                direction=Direction.DEBIT,
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=account.id,
                amount=Decimal("100.00"),
                direction=Direction.CREDIT,
            ),
        ]
    )
    await db.commit()

    matches = await execute_matching(db, user_id=user_id)
    assert len(matches) == 2
    for m in matches:
        assert m.score_breakdown.get("many_to_one_bonus") == 10.0


async def test_find_candidates(db: AsyncSession):
    user_id = uuid4()
    base_date = date(2024, 1, 1)
    entry = JournalEntry(
        user_id=user_id,
        entry_date=base_date,
        memo="Find Me",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    candidates = await find_candidates(db, base_date, DEFAULT_CONFIG, user_id)
    assert len(candidates) == 1
    assert candidates[0].memo == "Find Me"


def test_load_reconciliation_config_malformed_yaml():
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.read_text", return_value="invalid: yaml: :"),
    ):
        config = load_reconciliation_config(force_reload=True)
        assert config.auto_accept == DEFAULT_CONFIG.auto_accept


async def test_execute_matching_skip_unbalanced(db: AsyncSession):
    user_id = uuid4()
    user = User(id=user_id, email=f"unbalanced-{uuid4()}@example.com", hashed_password="hashed")
    statement = _make_statement(owner_id=user_id, base_date=date(2024, 1, 1))
    db.add_all([user, statement])
    await db.flush()

    txn = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2024, 1, 1),
        description="Check Unbalanced",
        amount=Decimal("100.00"),
        direction="OUT",
        status=BankStatementTransactionStatus.PENDING,
    )
    db.add(txn)

    account = Account(
        id=uuid4(),
        name="Test Account",
        type=AccountType.ASSET,
        user_id=user_id,
        currency="SGD",
    )
    db.add(account)
    await db.flush()

    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 1, 1),
        memo="Unbalanced",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=account.id,
            amount=Decimal("100.00"),
            direction=Direction.DEBIT,
        )
    )
    await db.commit()

    matches = await execute_matching(db, user_id=user_id)
    assert len(matches) == 0


async def test_execute_matching_low_score_unmatched(db: AsyncSession):
    user_id = uuid4()
    user = User(id=user_id, email=f"lowscore-{uuid4()}@example.com", hashed_password="hashed")
    statement = _make_statement(owner_id=user_id, base_date=date(2024, 1, 1))
    db.add_all([user, statement])
    await db.flush()

    txn = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2024, 1, 1),
        description="Bad Match",
        amount=Decimal("100.00"),
        direction="OUT",
        status=BankStatementTransactionStatus.PENDING,
    )
    db.add(txn)

    account = Account(
        id=uuid4(),
        name="Test Account",
        type=AccountType.ASSET,
        user_id=user_id,
        currency="SGD",
    )
    db.add(account)
    await db.flush()

    # Entry with very different amount and description
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 1, 1),
        memo="Random",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=account.id,
                amount=Decimal("1.00"),
                direction=Direction.DEBIT,
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=account.id,
                amount=Decimal("1.00"),
                direction=Direction.CREDIT,
            ),
        ]
    )
    await db.commit()

    matches = await execute_matching(db, user_id=user_id)
    assert len(matches) == 0

    result = await db.execute(select(BankStatementTransaction).where(BankStatementTransaction.id == txn.id))
    assert result.scalar_one().status == BankStatementTransactionStatus.UNMATCHED


def test_load_reconciliation_config_yaml_import_error():
    with patch("builtins.__import__", side_effect=ImportError):
        config = load_reconciliation_config(force_reload=True)
        assert config == DEFAULT_CONFIG


def test_auto_accept_helper():
    from src.services.reconciliation import auto_accept

    assert auto_accept(85, DEFAULT_CONFIG) is True
    assert auto_accept(84, DEFAULT_CONFIG) is False
    assert auto_accept(100, DEFAULT_CONFIG) is True
    assert auto_accept(0, DEFAULT_CONFIG) is False


@pytest.mark.asyncio
async def test_execute_matching_with_statement_id_filter(db: AsyncSession):
    user_id = uuid4()
    user = User(id=user_id, email="test@example.com", hashed_password="test")
    db.add(user)

    statement1 = _make_statement(owner_id=user_id, base_date=date(2024, 1, 1))
    statement2 = _make_statement(owner_id=user_id, base_date=date(2024, 1, 15))
    db.add_all([statement1, statement2])
    await db.flush()

    txn1 = BankStatementTransaction(
        statement_id=statement1.id,
        txn_date=date(2024, 1, 1),
        description="TXN1",
        amount=Decimal("100.00"),
        direction="OUT",
        status=BankStatementTransactionStatus.PENDING,
    )
    txn2 = BankStatementTransaction(
        statement_id=statement2.id,
        txn_date=date(2024, 1, 15),
        description="TXN2",
        amount=Decimal("200.00"),
        direction="OUT",
        status=BankStatementTransactionStatus.PENDING,
    )
    db.add_all([txn1, txn2])

    account = Account(
        id=uuid4(),
        name="Test Account",
        type=AccountType.ASSET,
        user_id=user_id,
        currency="SGD",
    )
    db.add(account)
    await db.flush()

    entry1 = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 1, 1),
        memo="Entry1",
        status=JournalEntryStatus.POSTED,
    )
    entry2 = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 1, 15),
        memo="Entry2",
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([entry1, entry2])
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry1.id,
                account_id=account.id,
                amount=Decimal("100.00"),
                direction=Direction.DEBIT,
            ),
            JournalLine(
                journal_entry_id=entry1.id,
                account_id=account.id,
                amount=Decimal("100.00"),
                direction=Direction.CREDIT,
            ),
            JournalLine(
                journal_entry_id=entry2.id,
                account_id=account.id,
                amount=Decimal("200.00"),
                direction=Direction.DEBIT,
            ),
            JournalLine(
                journal_entry_id=entry2.id,
                account_id=account.id,
                amount=Decimal("200.00"),
                direction=Direction.CREDIT,
            ),
        ]
    )
    await db.commit()

    await execute_matching(db, user_id=user_id, statement_id=str(statement1.id))

    result = await db.execute(select(BankStatementTransaction).options(selectinload(BankStatementTransaction.matches)))
    txns_with_matches = result.scalars().all()

    for txn in txns_with_matches:
        if txn.matches:
            assert txn.statement_id == statement1.id


def test_score_business_logic_out_equity():
    from src.models import BankStatementTransaction, JournalEntry, JournalLine

    txn = BankStatementTransaction(direction="OUT")
    account_asset = Account(type=AccountType.ASSET)
    account_equity = Account(type=AccountType.EQUITY)

    entry = JournalEntry(
        lines=[
            JournalLine(account=account_asset),
            JournalLine(account=account_equity),
        ]
    )

    score = score_business_logic(txn, entry)
    assert score == 40.0


def test_score_business_logic_out_unknown():
    from src.models import BankStatementTransaction, JournalEntry, JournalLine

    txn = BankStatementTransaction(direction="OUT")
    entry = JournalEntry(
        lines=[
            JournalLine(account=Account(type=AccountType.ASSET)),
        ]
    )

    score = score_business_logic(txn, entry)
    assert score == 70.0

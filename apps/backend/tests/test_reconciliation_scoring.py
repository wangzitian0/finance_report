"""Unit tests for reconciliation scoring utilities."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountEvent,
    AccountType,
    BankTransactionStatus,
    ConfidenceLevel,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
    ReconciliationMatch,
    ReconciliationStatus,
    Statement,
)
from src.services.reconciliation import (
    DEFAULT_CONFIG,
    auto_accept,
    build_many_to_one_groups,
    calculate_match_score,
    entry_total_amount,
    extract_merchant_tokens,
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


def _make_entry_with_types(account_types: list[AccountType]) -> JournalEntry:
    entry = JournalEntry(
        id=uuid4(),
        user_id=uuid4(),
        entry_date=date.today(),
        memo="Test entry",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    for index, account_type in enumerate(account_types):
        account = Account(
            id=uuid4(),
            user_id=uuid4(),
            name=f"Account {index}",
            type=account_type,
            currency="SGD",
        )
        line = JournalLine(
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=Direction.DEBIT,
            amount=Decimal("1.00"),
            currency="SGD",
        )
        line.account = account
        entry.lines.append(line)
    return entry


def _make_entry(amount: Decimal, entry_date: date) -> JournalEntry:
    entry = JournalEntry(
        id=uuid4(),
        user_id=uuid4(),
        entry_date=entry_date,
        memo="Amount entry",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    entry.lines.append(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=amount,
            currency="SGD",
        )
    )
    return entry


def test_load_reconciliation_config_reads_yaml_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_reconciliation_config()
    assert config.auto_accept == 85
    assert config.pending_review == 60

    monkeypatch.setenv("RECONCILIATION_AUTO_ACCEPT_THRESHOLD", "90")
    monkeypatch.setenv("RECONCILIATION_REVIEW_THRESHOLD", "70")
    updated = load_reconciliation_config(force_reload=True)
    assert updated.auto_accept == 90


def test_load_reconciliation_config_malformed_yaml(monkeypatch):
    """Test that malformed YAML falls back to defaults."""
    from pathlib import Path
    from src.services import reconciliation
    
    class MockPath:
        def exists(self): return True
        def read_text(self): return "invalid: : yaml"
        def resolve(self): return self
        @property
        def parents(self): return [self, self, self]
        def __truediv__(self, other): return self

    monkeypatch.setattr(reconciliation, "Path", lambda *args: MockPath())
    # Force reload to bypass cache
    config = reconciliation.load_reconciliation_config(force_reload=True)
    assert config.auto_accept == 85 # Default


def test_load_reconciliation_config_no_yaml_module(monkeypatch):
    """Test that missing yaml module falls back to defaults."""
    import sys
    from src.services import reconciliation
    
    # Mock Path to say file exists
    class MockPath:
        def exists(self): return True
        def resolve(self): return self
        @property
        def parents(self): return [self, self, self]
        def __truediv__(self, other): return self
        
    monkeypatch.setattr(reconciliation, "Path", lambda *args: MockPath())
    
    # Effectively hide yaml module from being used in the function's local scope
    # The function does 'import yaml' inside a try-except block
    with monkeypatch.context() as m:
        m.setitem(sys.modules, "yaml", None)
        config = reconciliation.load_reconciliation_config(force_reload=True)
        assert config.auto_accept == 85 # Default


def test_normalize_and_description_scoring() -> None:
    assert normalize_text("  ACME-CO.  ") == "acme co"
    assert score_description(None, "value") == 0.0
    assert score_description("   ", "value") == 0.0
    assert score_description("Coffee Shop", "coffee shop") >= 95.0


def test_extract_merchant_tokens() -> None:
    """Test merchant token extraction with various inputs."""
    # Basic extraction - takes significant words
    tokens = extract_merchant_tokens("STARBUCKS COFFEE DOWNTOWN")
    assert "starbucks" in tokens
    assert len(tokens) <= 3

    # Skip common prefixes
    tokens = extract_merchant_tokens("POS VISA DEBIT STARBUCKS")
    assert "starbucks" in tokens
    assert "pos" not in tokens
    assert "visa" not in tokens

    # Skip short words and numbers
    tokens = extract_merchant_tokens("123 AB COMPANY 456")
    assert "company" in tokens
    assert "123" not in tokens
    assert "ab" not in tokens  # Too short

    # Empty or all-skipped returns empty
    tokens = extract_merchant_tokens("POS VISA 12")
    assert tokens == []

    # Handle empty string
    tokens = extract_merchant_tokens("")
    assert tokens == []


def test_build_many_to_one_groups_skips_empty_descriptions() -> None:
    """build_many_to_one_groups should skip transactions with empty descriptions."""
    from dataclasses import dataclass

    @dataclass
    class MockTxn:
        description: str
        txn_date: date

    txns = [
        MockTxn(description="", txn_date=date(2024, 1, 1)),  # Empty - should skip
        MockTxn(description="   ", txn_date=date(2024, 1, 1)),  # Whitespace - should skip
        MockTxn(description="Regular payment", txn_date=date(2024, 1, 1)),  # No keyword - skip
        MockTxn(description="Batch settlement", txn_date=date(2024, 1, 1)),  # Has keyword
        MockTxn(description="Batch settlement", txn_date=date(2024, 1, 1)),  # Duplicate
    ]

    groups = build_many_to_one_groups(txns)  # type: ignore[arg-type]

    # Only the "Batch settlement" transactions should be grouped
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_score_amount_branches() -> None:
    config = DEFAULT_CONFIG
    assert score_amount(Decimal("100.00"), Decimal("100.00"), config) == 100.0
    assert score_amount(Decimal("100.00"), Decimal("100.40"), config) == 90.0
    assert score_amount(Decimal("100.00"), Decimal("104.00"), config) == 70.0
    assert score_amount(Decimal("1000.00"), Decimal("994.00"), config, is_multi=True) == 70.0
    assert score_amount(Decimal("0"), Decimal("10.00"), config) == 0.0
    assert score_amount(Decimal("100.00"), Decimal("160.00"), config) == 40.0


def test_score_date_branches() -> None:
    config = DEFAULT_CONFIG
    assert score_date(date(2024, 1, 1), date(2024, 1, 1), config) == 100.0
    assert score_date(date(2024, 1, 1), date(2024, 1, 3), config) == 90.0
    # Cross-month within date_days gets bonus (75 vs 70)
    assert score_date(date(2024, 1, 30), date(2024, 2, 4), config) == 75.0
    assert score_date(date(2024, 1, 1), date(2024, 2, 1), config) == 0.0


@pytest.mark.parametrize(
    ("direction", "types", "expected"),
    [
        ("IN", [AccountType.ASSET, AccountType.INCOME], 100.0),
        ("IN", [AccountType.ASSET, AccountType.LIABILITY], 85.0),
        ("IN", [AccountType.ASSET, AccountType.EQUITY], 75.0),
        ("IN", [AccountType.ASSET], 70.0),
        ("IN", [AccountType.EXPENSE], 40.0),
        ("OUT", [AccountType.ASSET, AccountType.EXPENSE], 100.0),
        ("OUT", [AccountType.ASSET, AccountType.LIABILITY], 90.0),
        ("OUT", [AccountType.ASSET], 70.0),
        ("OUT", [AccountType.INCOME], 40.0),
        ("OTHER", [AccountType.ASSET], 50.0),
    ],
)
def test_score_business_logic_variants(
    direction: str, types: list[AccountType], expected: float
) -> None:
    txn = AccountEvent(
        statement_id=uuid4(),
        txn_date=date.today(),
        description="Test",
        amount=Decimal("10.00"),
        direction=direction,
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    entry = _make_entry_with_types(types)
    assert score_business_logic(txn, entry) == expected


def test_weighted_total_and_balance_helpers() -> None:
    scores = {
        "amount": 100.0,
        "date": 100.0,
        "description": 100.0,
        "business": 100.0,
        "history": 0.0,
    }
    assert weighted_total(scores, DEFAULT_CONFIG) == 95

    entry = JournalEntry(
        id=uuid4(),
        user_id=uuid4(),
        entry_date=date.today(),
        memo="Balance check",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    entry.lines.append(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("50.00"),
            currency="SGD",
        )
    )
    entry.lines.append(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=uuid4(),
            direction=Direction.CREDIT,
            amount=Decimal("50.00"),
            currency="SGD",
        )
    )
    assert entry_total_amount(entry) == Decimal("50.00")
    assert is_entry_balanced(entry)

    entry.lines.append(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("10.00"),
            currency="SGD",
        )
    )
    assert not is_entry_balanced(entry)


def test_prune_candidates_orders_and_limits() -> None:
    txn_date = date.today()
    entry_close = _make_entry(Decimal("100.00"), txn_date)
    entry_far_amount = _make_entry(Decimal("90.00"), txn_date)
    entry_far_date = _make_entry(Decimal("100.00"), txn_date - timedelta(days=2))

    candidates = [entry_far_date, entry_far_amount, entry_close]
    pruned = prune_candidates(
        candidates,
        txn_date=txn_date,
        target_amount=Decimal("100.00"),
        limit=2,
    )
    # New heuristic prioritizes exact amount match over date:
    # entry_close: exact_match=0, amount_diff=0, date_diff=0
    # entry_far_date: exact_match=0, amount_diff=0, date_diff=2
    # entry_far_amount: exact_match=1 (>1% diff), amount_diff=10, date_diff=0
    assert pruned == [entry_close, entry_far_date]
    assert (
        prune_candidates(
            candidates,
            txn_date=txn_date,
            target_amount=Decimal("100.00"),
            limit=5,
        )
        == candidates
    )


@pytest.mark.asyncio
async def test_score_pattern_variants(db: AsyncSession) -> None:
    txn_empty = AccountEvent(
        statement_id=uuid4(),
        txn_date=date.today(),
        description="",
        amount=Decimal("10.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.MEDIUM,
    )
    assert await score_pattern(db, txn_empty, DEFAULT_CONFIG, user_id=uuid4()) == 0.0

    txn_no_history = AccountEvent(
        statement_id=uuid4(),
        txn_date=date.today(),
        description="Coffee Shop",
        amount=Decimal("10.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.MEDIUM,
    )
    assert await score_pattern(db, txn_no_history, DEFAULT_CONFIG, user_id=uuid4()) == 0.0

    statement = Statement(
        user_id=uuid4(),  # Using a valid UUID for NOT NULL constraint
        account_id=None,
        file_path="statements/history.pdf",
        file_hash="hash_history",
        original_filename="history.pdf",
        institution="Test Bank",
        account_last4="7890",
        currency="SGD",
        period_start=date.today(),
        period_end=date.today(),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
    )
    db.add(statement)
    await db.flush()

    past_txn = AccountEvent(
        statement_id=statement.id,
        txn_date=date.today(),
        description="Coffee Shop",
        amount=Decimal("10.00"),
        direction="OUT",
        status=BankTransactionStatus.MATCHED,
        confidence=ConfidenceLevel.HIGH,
    )
    db.add(past_txn)
    await db.flush()

    match = ReconciliationMatch(
        bank_txn_id=past_txn.id,
        journal_entry_ids=[],
        match_score=88,
        score_breakdown={"amount": 100.0},
        status=ReconciliationStatus.ACCEPTED,
    )
    db.add(match)
    await db.commit()

    txn_match = AccountEvent(
        statement_id=statement.id,
        txn_date=date.today(),
        description="Coffee Shop",
        amount=Decimal("10.05"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    txn_miss = AccountEvent(
        statement_id=statement.id,
        txn_date=date.today(),
        description="Coffee Shop",
        amount=Decimal("10.50"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )

    assert await score_pattern(db, txn_match, DEFAULT_CONFIG, user_id=statement.user_id) == 80.0
    assert await score_pattern(db, txn_miss, DEFAULT_CONFIG, user_id=statement.user_id) == 40.0


@pytest.mark.asyncio
async def test_calculate_match_score_many_to_one_bonus(db: AsyncSession) -> None:
    user_id = uuid4()
    bank = Account(
        id=uuid4(),
        user_id=user_id,
        name="Bank",
        type=AccountType.ASSET,
        currency="SGD",
    )
    expense = Account(
        id=uuid4(),
        user_id=user_id,
        name="Expense",
        type=AccountType.EXPENSE,
        currency="SGD",
    )
    entry = JournalEntry(
        id=uuid4(),
        user_id=user_id,
        entry_date=date.today(),
        memo="Batch payment",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    debit_line = JournalLine(
        journal_entry_id=entry.id,
        account_id=expense.id,
        direction=Direction.DEBIT,
        amount=Decimal("100.00"),
        currency="SGD",
    )
    debit_line.account = expense
    credit_line = JournalLine(
        journal_entry_id=entry.id,
        account_id=bank.id,
        direction=Direction.CREDIT,
        amount=Decimal("100.00"),
        currency="SGD",
    )
    credit_line.account = bank
    entry.lines.extend([debit_line, credit_line])

    # We need a statement to link the txn to a user_id for the history check query
    statement = Statement(
        user_id=user_id,
        file_path="dummy",
        file_hash="dummy",
        original_filename="dummy.pdf",
        institution="Dummy",
        currency="SGD",
        period_start=date.today(),
        period_end=date.today(),
        opening_balance=Decimal("0"),
        closing_balance=Decimal("0"),
    )
    db.add(statement)
    await db.flush()

    txn = AccountEvent(
        statement_id=statement.id,
        txn_date=date.today(),
        description="Batch payment",
        amount=Decimal("100.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    candidate = await calculate_match_score(
        db,
        txn,
        [entry],
        DEFAULT_CONFIG,
        user_id=user_id,
        is_multi=True,
        is_many_to_one=True,
        amount_override=Decimal("100.00"),
    )
    assert candidate.journal_entry_ids == [str(entry.id)]
    assert candidate.breakdown["many_to_one_bonus"] == 10.0
    assert auto_accept(candidate.score, DEFAULT_CONFIG)



"""Unit tests for reconciliation scoring utilities."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.reconciliation import (
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
    import src.reconciliation as reconciliation
    from src.reconciliation.base import config as reconciliation_config

    class MockPath:
        def exists(self):
            return True

        def read_text(self):
            return "invalid: : yaml"

        def resolve(self):
            return self

        @property
        def parents(self):
            return [self, self, self]

        def __truediv__(self, other):
            return self

    monkeypatch.setattr(reconciliation_config, "Path", lambda *args: MockPath())
    # Force reload to bypass cache
    config = reconciliation.load_reconciliation_config(force_reload=True)
    assert config.auto_accept == 85  # Default


def test_load_reconciliation_config_no_yaml_module(monkeypatch):
    """Test that missing yaml module falls back to defaults."""
    import sys

    import src.reconciliation as reconciliation
    from src.reconciliation.base import config as reconciliation_config

    # Mock Path to say file exists
    class MockPath:
        def exists(self):
            return True

        def resolve(self):
            return self

        @property
        def parents(self):
            return [self, self, self]

        def __truediv__(self, other):
            return self

    monkeypatch.setattr(reconciliation_config, "Path", lambda *args: MockPath())

    # Effectively hide yaml module from being used in the function's local scope
    # The function does 'import yaml' inside a try-except block
    with monkeypatch.context() as m:
        m.setitem(sys.modules, "yaml", None)
        config = reconciliation.load_reconciliation_config(force_reload=True)
        assert config.auto_accept == 85  # Default


def test_normalize_and_description_scoring(ac_evidence) -> None:
    """AC-reconciliation.matching-core.4: [AC4.1.4] Test description similarity."""
    assert normalize_text("  ACME-CO.  ") == "acme co"
    assert score_description(None, "value") == 0.0
    assert score_description("   ", "value") == 0.0
    # Description Similarity [AC4.1.4]
    similarity = score_description("Coffee Shop", "coffee shop")
    assert similarity >= 95.0
    # Emit measured behavioral evidence for the ratchet gate. The score is the
    # measured similarity (0-100) normalised to [0,1] — not a hand-assigned grade.
    ac_evidence(
        ac_id="AC-reconciliation.matching-core.4",
        score=similarity / 100.0,
        metric="description_similarity_pct",
        comment=(f"score_description('Coffee Shop','coffee shop')={similarity:.1f}/100"),
        provenance="deterministic",
    )


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


def test_score_amount_branches(ac_evidence) -> None:
    """AC-reconciliation.matching-core.1: [AC4.1.1] [AC4.1.3] Test score_amount logic."""
    config = DEFAULT_CONFIG
    # Exact Match [AC4.1.1]
    exact = score_amount(Decimal("100.00"), Decimal("100.00"), config)
    assert exact == 100.0
    # Tolerance match [AC4.1.3]
    tolerance = score_amount(Decimal("100.00"), Decimal("100.40"), config)
    assert tolerance == 90.0
    assert score_amount(Decimal("100.00"), Decimal("104.00"), config) == 70.0
    assert score_amount(Decimal("1000.00"), Decimal("994.00"), config, is_multi=True) == 70.0
    assert score_amount(Decimal("0"), Decimal("10.00"), config) == 0.0
    assert score_amount(Decimal("100.00"), Decimal("160.00"), config) == 40.0
    # Measured evidence: exact-match amount score (100/100) normalised to [0,1].
    ac_evidence(
        ac_id="AC-reconciliation.matching-core.1",
        score=exact / 100.0,
        metric="amount_score_pct",
        comment=f"score_amount(100.00, 100.00)={exact:.1f}/100 (exact match)",
        provenance="deterministic",
    )
    # Measured evidence: in-tolerance amount score (0.40 delta -> 90/100).
    ac_evidence(
        ac_id="AC-reconciliation.matching-core.3",
        score=tolerance / 100.0,
        metric="amount_score_pct",
        comment=f"score_amount(100.00, 100.40)={tolerance:.1f}/100 (within tolerance)",
        provenance="deterministic",
    )


def test_amount_tolerance_0_10_boundary(ac_evidence) -> None:
    """AC-reconciliation.source-type-transfer.1: AC4.6.1: Absolute amount delta of 0.10 passes, but 0.11 fails."""
    config = DEFAULT_CONFIG

    inside = score_amount(Decimal("10.00"), Decimal("10.10"), config)
    outside = score_amount(Decimal("10.00"), Decimal("10.11"), config)
    assert inside == 90.0
    assert outside < 90.0
    # Measured evidence: the boundary holds (delta 0.10 scores 90, delta 0.11
    # drops below). Score is 1.0 iff both sides of the boundary behave.
    ac_evidence(
        ac_id="AC-reconciliation.source-type-transfer.1",
        score=1.0 if (inside == 90.0 and outside < 90.0) else 0.0,
        metric="amount_tolerance_boundary_holds",
        comment=f"delta 0.10 -> {inside:.1f}/100, delta 0.11 -> {outside:.1f}/100",
        provenance="deterministic",
    )


def test_score_date_branches(ac_evidence) -> None:
    """AC-reconciliation.matching-core.2: [AC4.1.2] Test score_date logic."""
    config = DEFAULT_CONFIG
    # Exact Date
    assert score_date(date(2024, 1, 1), date(2024, 1, 1), config) == 100.0
    # Fuzzy Date [AC4.1.2]
    fuzzy = score_date(date(2024, 1, 1), date(2024, 1, 3), config)
    assert fuzzy == 90.0
    # Cross-month within date_days gets bonus (75 vs 70)
    assert score_date(date(2024, 1, 30), date(2024, 2, 4), config) == 75.0
    assert score_date(date(2024, 1, 1), date(2024, 2, 1), config) == 0.0
    # Measured evidence: a 2-day gap scores 90/100 on the fuzzy-date curve.
    ac_evidence(
        ac_id="AC-reconciliation.matching-core.2",
        score=fuzzy / 100.0,
        metric="date_score_pct",
        comment=f"score_date(2024-01-01, 2024-01-03)={fuzzy:.1f}/100 (2-day gap)",
        provenance="deterministic",
    )


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
def test_score_business_logic_variants(direction: str, types: list[AccountType], expected: float) -> None:
    txn = AtomicTransaction(
        user_id=uuid4(),
        txn_date=date.today(),
        description="Test",
        amount=Decimal("10.00"),
        direction=direction,
        currency="SGD",
        dedup_hash=uuid4().hex,
        source_documents=[],
    )
    entry = _make_entry_with_types(types)
    assert score_business_logic(txn, entry) == expected


def test_weighted_total_and_balance_helpers() -> None:
    """AC-reconciliation.score.1."""
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


async def test_score_pattern_variants(db: AsyncSession, test_user) -> None:
    txn_empty = AtomicTransaction(
        user_id=uuid4(),
        txn_date=date.today(),
        description="",
        amount=Decimal("10.00"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash=uuid4().hex,
        source_documents=[],
    )
    assert await score_pattern(db, txn_empty, DEFAULT_CONFIG, user_id=uuid4()) == 0.0

    txn_no_history = AtomicTransaction(
        user_id=uuid4(),
        txn_date=date.today(),
        description="Coffee Shop",
        amount=Decimal("10.00"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash=uuid4().hex,
        source_documents=[],
    )
    assert await score_pattern(db, txn_no_history, DEFAULT_CONFIG, user_id=uuid4()) == 0.0

    user_id = test_user.id
    past_txn = AtomicTransaction(
        user_id=user_id,
        txn_date=date.today(),
        description="Coffee Shop",
        amount=Decimal("10.00"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash=uuid4().hex,
        source_documents=[],
    )
    db.add(past_txn)
    await db.flush()

    match = ReconciliationMatch(
        atomic_txn_id=past_txn.id,
        journal_entry_ids=[],
        match_score=88,
        score_breakdown={"amount": 100.0},
        status=ReconciliationStatus.ACCEPTED,
    )
    db.add(match)
    await db.commit()

    txn_match = AtomicTransaction(
        user_id=user_id,
        txn_date=date.today(),
        description="Coffee Shop",
        amount=Decimal("10.05"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash=uuid4().hex,
        source_documents=[],
    )
    txn_miss = AtomicTransaction(
        user_id=user_id,
        txn_date=date.today(),
        description="Coffee Shop",
        amount=Decimal("10.50"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash=uuid4().hex,
        source_documents=[],
    )

    assert await score_pattern(db, txn_match, DEFAULT_CONFIG, user_id=user_id) == 80.0
    assert await score_pattern(db, txn_miss, DEFAULT_CONFIG, user_id=user_id) == 40.0


async def test_calculate_match_score_many_to_one_bonus(db: AsyncSession) -> None:
    """AC-reconciliation.group-matching.2."""
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

    txn = AtomicTransaction(
        user_id=user_id,
        txn_date=date.today(),
        description="Batch payment",
        amount=Decimal("100.00"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash=uuid4().hex,
        source_documents=[],
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

"""Unit tests for reconciliation scoring helper functions.

[AC12.18.7.2] Pure unit tests for _find_transfer_candidates,
_find_many_to_one_candidates, and _find_normal_candidates.
No DB access required — these are pure scoring functions.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from src.extraction.orm.layer2 import AtomicTransaction, TransactionDirection
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.reconciliation import (
    DEFAULT_CONFIG,
    _find_many_to_one_candidates,
    _find_normal_candidates,
    _find_transfer_candidates,
)


def _make_txn(
    *,
    description: str = "Test Payment",
    amount: Decimal = Decimal("100.00"),
    direction: str = "OUT",
    txn_date: date = date(2024, 1, 1),
    statement_id=None,
) -> AtomicTransaction:
    return AtomicTransaction(
        id=uuid4(),
        user_id=uuid4(),
        txn_date=txn_date,
        description=description,
        amount=amount,
        direction=TransactionDirection(direction),
        currency="SGD",
        dedup_hash=uuid4().hex,
        source_documents=[{"doc_id": str(statement_id or uuid4()), "doc_type": "bank_statement"}],
    )


def _make_entry(
    *,
    memo: str = "Test Entry",
    amount: Decimal = Decimal("100.00"),
    entry_date: date = date(2024, 1, 1),
    user_id=None,
    account_type_debit: AccountType = AccountType.EXPENSE,
    account_type_credit: AccountType = AccountType.ASSET,
) -> JournalEntry:
    uid = user_id or uuid4()
    entry = JournalEntry(
        id=uuid4(),
        user_id=uid,
        entry_date=entry_date,
        memo=memo,
        status=JournalEntryStatus.POSTED,
    )
    acct_debit = Account(type=account_type_debit)
    acct_credit = Account(type=account_type_credit)
    entry.lines = [
        JournalLine(
            account=acct_debit,
            direction=Direction.DEBIT,
            amount=amount,
        ),
        JournalLine(
            account=acct_credit,
            direction=Direction.CREDIT,
            amount=amount,
        ),
    ]
    return entry


class TestFindTransferCandidates:
    """AC-reconciliation.candidate-matching.1: [AC12.18.7.2] _find_transfer_candidates returns transfer pairs."""

    def test_find_transfer_candidates_returns_pair(self) -> None:
        """Transfer-pattern transactions are identified with score=100."""

        txn_out = _make_txn(
            description="Transfer to savings account",
            amount=Decimal("500.00"),
            direction="OUT",
        )
        txn_normal = _make_txn(
            description="Coffee Shop payment",
            amount=Decimal("5.00"),
            direction="OUT",
        )

        results = _find_transfer_candidates(
            pending_txns=[txn_out, txn_normal],
            atomic_txns=[],
            pattern_scores={},
            config=DEFAULT_CONFIG,
        )

        assert len(results) == 1
        bank_txn, candidate, paired = results[0]
        assert bank_txn is txn_out
        assert candidate.score == 100
        assert "transfer_out" in candidate.breakdown
        assert paired is None

    def test_find_transfer_candidates_in_direction(self) -> None:
        """Transfer IN direction uses transfer_in key."""
        txn_in = _make_txn(
            description="Transfer from checking",
            amount=Decimal("200.00"),
            direction="IN",
        )

        results = _find_transfer_candidates(
            pending_txns=[txn_in],
            atomic_txns=[],
            pattern_scores={},
            config=DEFAULT_CONFIG,
        )

        assert len(results) == 1
        _, candidate, _ = results[0]
        assert "transfer_in" in candidate.breakdown

    def test_find_transfer_candidates_empty_for_normal(self) -> None:
        """Non-transfer transactions produce empty results."""
        txn = _make_txn(description="Grocery Store", direction="OUT")

        results = _find_transfer_candidates(
            pending_txns=[txn],
            atomic_txns=[],
            pattern_scores={},
            config=DEFAULT_CONFIG,
        )

        assert results == []


class TestFindNormalCandidates:
    """[AC12.18.7.2] _find_normal_candidates returns best matches."""

    def test_find_normal_candidates_returns_best_match(self) -> None:
        """Exact match on amount/date/description scores high."""
        txn = _make_txn(
            description="Salary Payment",
            amount=Decimal("1000.00"),
            direction="IN",
            txn_date=date(2024, 1, 15),
        )
        entry = _make_entry(
            memo="Salary Payment",
            amount=Decimal("1000.00"),
            entry_date=date(2024, 1, 15),
            account_type_debit=AccountType.ASSET,
            account_type_credit=AccountType.INCOME,
        )

        results = _find_normal_candidates(
            pending_txns=[txn],
            atomic_txns=[entry],
            pattern_scores={},
            config=DEFAULT_CONFIG,
            base_currency="SGD",
        )

        assert len(results) == 1
        bank_txn, candidate = results[0]
        assert bank_txn is txn
        assert candidate.score >= DEFAULT_CONFIG.auto_accept
        assert str(entry.id) in candidate.journal_entry_ids

    def test_find_normal_candidates_low_score_excluded(self) -> None:
        """Transactions with no good match are excluded from results."""
        txn = _make_txn(
            description="Random Purchase",
            amount=Decimal("999.00"),
            direction="OUT",
            txn_date=date(2024, 1, 1),
        )

        entry = _make_entry(
            memo="Something Else",
            amount=Decimal("1.00"),
            entry_date=date(2024, 1, 1),
        )

        results = _find_normal_candidates(
            pending_txns=[txn],
            atomic_txns=[entry],
            pattern_scores={},
            config=DEFAULT_CONFIG,
            base_currency="SGD",
        )

        assert len(results) == 0

    def test_find_normal_candidates_multi_entry_combination(self) -> None:
        """Two entries that sum to txn amount produce a multi-entry match."""
        txn = _make_txn(
            description="Split Payment",
            amount=Decimal("100.00"),
            direction="OUT",
            txn_date=date(2024, 4, 5),
        )
        entry_a = _make_entry(
            memo="Split Payment",
            amount=Decimal("50.00"),
            entry_date=date(2024, 4, 5),
        )
        entry_b = _make_entry(
            memo="Split Payment",
            amount=Decimal("50.00"),
            entry_date=date(2024, 4, 5),
        )

        results = _find_normal_candidates(
            pending_txns=[txn],
            atomic_txns=[entry_a, entry_b],
            pattern_scores={},
            config=DEFAULT_CONFIG,
            base_currency="SGD",
        )

        assert len(results) == 1
        _, candidate = results[0]
        assert candidate.breakdown.get("multi_entry") == 1
        assert len(candidate.journal_entry_ids) == 2

    def test_find_normal_candidates_no_entries(self) -> None:
        """No atomic_txns means no results."""
        txn = _make_txn(description="Test", amount=Decimal("100.00"))

        results = _find_normal_candidates(
            pending_txns=[txn],
            atomic_txns=[],
            pattern_scores={},
            config=DEFAULT_CONFIG,
            base_currency="SGD",
        )

        assert results == []

    def test_find_normal_candidates_three_entry_combination(self) -> None:
        """Three balanced entries can match one bank transaction."""
        txn = _make_txn(
            description="Vendor ABC combined settlement",
            amount=Decimal("300.00"),
            direction="OUT",
            txn_date=date(2024, 1, 1),
        )
        entries = [
            _make_entry(memo="Vendor ABC part 1", amount=Decimal("100.00")),
            _make_entry(memo="Vendor ABC part 2", amount=Decimal("100.00")),
            _make_entry(memo="Vendor ABC part 3", amount=Decimal("100.00")),
        ]

        results = _find_normal_candidates(
            pending_txns=[txn],
            atomic_txns=entries,
            pattern_scores={"vendor": 90.0},
            config=DEFAULT_CONFIG,
            base_currency="SGD",
        )

        assert len(results) == 1
        _, candidate = results[0]
        assert len(candidate.journal_entry_ids) == 3
        assert candidate.breakdown["multi_entry"] == 2


class TestFindManyToOneCandidates:
    """[AC12.18.7.2] _find_many_to_one_candidates groups batch transactions."""

    def test_find_many_to_one_candidates_groups_correctly(self) -> None:
        """Batch transactions group and match against a summed entry."""
        stmt_id = uuid4()
        txn_a = _make_txn(
            description="Batch settlement ACME",
            amount=Decimal("40.00"),
            direction="OUT",
            txn_date=date(2024, 4, 1),
            statement_id=stmt_id,
        )
        txn_b = _make_txn(
            description="Batch settlement ACME",
            amount=Decimal("60.00"),
            direction="OUT",
            txn_date=date(2024, 4, 1),
            statement_id=stmt_id,
        )
        entry = _make_entry(
            memo="Batch settlement ACME",
            amount=Decimal("100.00"),
            entry_date=date(2024, 4, 1),
        )

        results = _find_many_to_one_candidates(
            pending_txns=[txn_a, txn_b],
            atomic_txns=[entry],
            pattern_scores={},
            config=DEFAULT_CONFIG,
            base_currency="SGD",
        )

        assert len(results) == 1
        rep_txn, candidate = results[0]

        assert rep_txn in (txn_a, txn_b)
        assert candidate.score >= DEFAULT_CONFIG.pending_review
        assert candidate.breakdown.get("many_to_one_bonus") == 10.0
        assert candidate.breakdown.get("group_total") == "100.00"

    def test_find_many_to_one_candidates_no_batch_keywords(self) -> None:
        """Non-batch transactions don't form groups."""
        txn_a = _make_txn(
            description="Coffee Shop",
            amount=Decimal("5.00"),
            txn_date=date(2024, 1, 1),
        )
        txn_b = _make_txn(
            description="Coffee Shop",
            amount=Decimal("5.00"),
            txn_date=date(2024, 1, 1),
        )
        entry = _make_entry(
            memo="Coffee",
            amount=Decimal("10.00"),
            entry_date=date(2024, 1, 1),
        )

        results = _find_many_to_one_candidates(
            pending_txns=[txn_a, txn_b],
            atomic_txns=[entry],
            pattern_scores={},
            config=DEFAULT_CONFIG,
            base_currency="SGD",
        )

        assert results == []

    def test_find_many_to_one_candidates_no_entries(self) -> None:
        """No journal entries means no results."""
        txn_a = _make_txn(
            description="Batch settlement ACME",
            amount=Decimal("40.00"),
            txn_date=date(2024, 4, 1),
        )
        txn_b = _make_txn(
            description="Batch settlement ACME",
            amount=Decimal("60.00"),
            txn_date=date(2024, 4, 1),
        )

        results = _find_many_to_one_candidates(
            pending_txns=[txn_a, txn_b],
            atomic_txns=[],
            pattern_scores={},
            config=DEFAULT_CONFIG,
            base_currency="SGD",
        )

        assert results == []

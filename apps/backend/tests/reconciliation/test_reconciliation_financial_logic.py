"""AC4.9: Reconciliation financial logic tests."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalLine
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.reconciliation import DEFAULT_CONFIG, calculate_match_score


async def test_AC4_9_1_entry_total_uses_bank_side_line_for_outflow(db):
    """AC-reconciliation.bank-side-amount.1: AC4.9.1: Matching amount uses the bank/cash line for bank outflows."""
    bank = Account(id=uuid4(), user_id=uuid4(), name="Checking", type=AccountType.ASSET, currency="SGD")
    expense = Account(id=uuid4(), user_id=bank.user_id, name="Expense", type=AccountType.EXPENSE, currency="SGD")
    clearing = Account(id=uuid4(), user_id=bank.user_id, name="Clearing", type=AccountType.ASSET, currency="SGD")
    payable = Account(id=uuid4(), user_id=bank.user_id, name="Payable", type=AccountType.LIABILITY, currency="SGD")
    entry = JournalEntry(id=uuid4(), user_id=bank.user_id, entry_date=date(2026, 1, 5), memo="Vendor split")
    entry.lines = [
        JournalLine(account=expense, direction=Direction.DEBIT, amount=Decimal("100.00")),
        JournalLine(account=clearing, direction=Direction.DEBIT, amount=Decimal("20.00")),
        JournalLine(account=bank, direction=Direction.CREDIT, amount=Decimal("100.00")),
        JournalLine(account=payable, direction=Direction.CREDIT, amount=Decimal("20.00")),
    ]
    transaction = AtomicTransaction(
        id=uuid4(),
        user_id=bank.user_id,
        txn_date=date(2026, 1, 5),
        description="Vendor payment",
        amount=Decimal("100.00"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash=uuid4().hex,
        source_documents=[{"doc_id": str(uuid4()), "doc_type": "bank_statement"}],
    )

    candidate = await calculate_match_score(
        db,
        transaction,
        [entry],
        DEFAULT_CONFIG,
        user_id=bank.user_id,
        history_score_override=0,
    )

    assert candidate.breakdown["amount"] == 100.0

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.advisor.orm.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus
from src.extraction import BankStatementStatus, DocumentType, TransactionDirection, UploadedDocument
from src.extraction.base.validation import compute_confidence_score, route_by_threshold
from src.extraction.orm.layer2 import AtomicPosition, AtomicTransaction
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.portfolio import DividendIncome
from src.pricing import MarketDataOverride
from src.pricing.orm.market_data import FxRate


@pytest.mark.parametrize(
    ("factory", "expected_substrings"),
    [
        (lambda _sid: ChatSession(id=uuid4(), user_id=uuid4(), title="Test Session", status=ChatSessionStatus.ACTIVE), ("ChatSession", "status=active")),
        (lambda sid: ChatMessage(id=uuid4(), session_id=sid, role=ChatMessageRole.USER, content="Hello"), ("ChatMessage", "user")),
        (lambda _sid: FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.35"), rate_date=date(2024, 1, 1), source="test"), ("FxRate", "USD/SGD", "1.35")),
        (lambda _sid: Account(id=uuid4(), name="Cash", type=AccountType.ASSET, code="1000", currency="USD", user_id=uuid4()), ("<Account Cash (ASSET)>",)),
        (lambda _sid: JournalEntry(id=uuid4(), user_id=uuid4(), entry_date=date(2024, 1, 15), memo="This is a very long memo that should be truncated in the repr", status=JournalEntryStatus.DRAFT), ("<JournalEntry 2024-01-15 - This is a very long memo that >",)),
        (lambda _sid: JournalLine(id=uuid4(), journal_entry_id=uuid4(), account_id=uuid4(), direction=Direction.DEBIT, amount="1000.00", currency="USD"), ("<JournalLine DEBIT 1000.00 USD>",)),
        (lambda _sid: UploadedDocument(id=uuid4(), user_id=uuid4(), original_filename="statement.pdf", document_type=DocumentType.BANK_STATEMENT, file_path="uploads/statement.pdf", file_hash="abc123"), ("<UploadedDocument statement.pdf (bank_statement)>",)),
        (lambda _sid: AtomicTransaction(id=uuid4(), user_id=uuid4(), txn_date=date(2024, 1, 15), direction=TransactionDirection.IN, amount="500.00", currency="SGD", description="Test transaction"), ("<AtomicTransaction 2024-01-15 IN 500.00 SGD>",)),
        (lambda _sid: AtomicPosition(id=uuid4(), user_id=uuid4(), snapshot_date=date(2024, 1, 15), asset_identifier="AAPL", quantity="100", market_value="15000.00", currency="USD"), ("<AtomicPosition 2024-01-15 AAPL 100 @ 15000.00 USD>",)),
        (lambda _sid: DividendIncome(payment_date=date(2024, 3, 15), amount="125.50", currency="USD"), ("<DividendIncome 2024-03-15 125.50 USD>",)),
        (lambda _sid: MarketDataOverride(asset_identifier="AAPL", price="185.50", price_date=date(2024, 3, 15)), ("<MarketDataOverride AAPL 185.50 on 2024-03-15>",)),
    ],
)
def test_model_reprs(factory, expected_substrings: tuple[str, ...]) -> None:
    sid = uuid4()
    rendered = repr(factory(sid))
    assert all(part in rendered for part in expected_substrings)
    if expected_substrings == ("ChatMessage", "user"):
        assert str(sid) in rendered


def test_chat_enums_and_extraction_threshold_helpers() -> None:
    assert (ChatSession.__table__.c.status.type.enums, ChatMessage.__table__.c.role.type.enums) == (
        ["active", "deleted"],
        ["user", "assistant", "system"],
    )
    assert (
        route_by_threshold(85, True),
        route_by_threshold(60, True),
        route_by_threshold(50, False),
        route_by_threshold(50, True),
    ) == (
        BankStatementStatus.APPROVED,
        BankStatementStatus.PARSED,
        BankStatementStatus.PARSED,
        BankStatementStatus.UPLOADED,
    )
    score = compute_confidence_score(
        {"description": "Test", "amount": "not_a_number", "transaction_date": "2024-01-01"},
        {"balance_valid": False, "difference": "invalid_decimal"},
    )
    assert isinstance(score, int) and 0 <= score <= 100

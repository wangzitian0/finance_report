from datetime import date
from decimal import Decimal
from uuid import uuid4

from src.advisor.orm.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus
from src.pricing.orm.market_data import FxRate


def test_chat_session_repr():
    """AC6.4.1: ChatSession repr includes status."""
    session = ChatSession(
        id=uuid4(),
        user_id=uuid4(),
        title="Test Session",
        status=ChatSessionStatus.ACTIVE,
    )
    repr_str = repr(session)
    assert "ChatSession" in repr_str
    assert "status=active" in repr_str


def test_chat_message_repr():
    """AC6.4.1: ChatMessage repr includes role and session ID."""
    session_id = uuid4()
    message = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role=ChatMessageRole.USER,
        content="Hello",
    )
    repr_str = repr(message)
    assert "ChatMessage" in repr_str
    assert "user" in repr_str
    assert str(session_id) in repr_str


def test_chat_model_enums_match_migration_values():
    """AC6.4.1: Chat ORM enums persist the lowercase PostgreSQL enum values."""
    assert ChatSession.__table__.c.status.type.enums == ["active", "deleted"]
    assert ChatMessage.__table__.c.role.type.enums == ["user", "assistant", "system"]


def test_fx_rate_repr():
    fx_rate = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.35"),
        rate_date=date(2024, 1, 1),
        source="test",
    )
    repr_str = repr(fx_rate)
    assert "FxRate" in repr_str
    assert "USD/SGD" in repr_str
    assert "1.35" in repr_str


def test_validation_route_by_threshold():
    from src.extraction.base.validation import route_by_threshold
    from src.models.statement_enums import BankStatementStatus

    assert route_by_threshold(85, True) == BankStatementStatus.APPROVED
    assert route_by_threshold(60, True) == BankStatementStatus.PARSED
    # #1141: balance-invalid bank statements route to PARSED (review), not UPLOADED.
    assert route_by_threshold(50, False) == BankStatementStatus.PARSED
    assert route_by_threshold(50, True) == BankStatementStatus.UPLOADED


def test_validation_confidence_with_invalid_amount():
    from src.extraction.base.validation import compute_confidence_score

    extracted_data = {
        "description": "Test",
        "amount": "not_a_number",
        "transaction_date": "2024-01-01",
    }

    balance_result = {
        "balance_valid": False,
        "difference": "invalid_decimal",
    }

    score = compute_confidence_score(extracted_data, balance_result)
    assert isinstance(score, int)
    assert 0 <= score <= 100


def test_account_repr():
    """
    GIVEN an Account instance
    WHEN calling repr() on it
    THEN it returns a formatted string with name and type
    """
    from src.ledger import Account, AccountType

    account = Account(
        id=uuid4(),
        name="Cash",
        type=AccountType.ASSET,
        code="1000",
        currency="USD",
        user_id=uuid4(),
    )
    result = repr(account)
    assert result == "<Account Cash (ASSET)>"


def test_journal_entry_repr():
    """
    GIVEN a JournalEntry instance
    WHEN calling repr() on it
    THEN it returns a formatted string with date and truncated memo
    """
    from src.ledger import JournalEntry, JournalEntryStatus

    entry = JournalEntry(
        id=uuid4(),
        user_id=uuid4(),
        entry_date=date(2024, 1, 15),
        memo="This is a very long memo that should be truncated in the repr",
        status=JournalEntryStatus.DRAFT,
    )
    result = repr(entry)
    # memo[:30] = "This is a very long memo that " (30 chars, ends with space)
    assert result == "<JournalEntry 2024-01-15 - This is a very long memo that >"


def test_journal_line_repr():
    """
    GIVEN a JournalLine instance
    WHEN calling repr() on it
    THEN it returns a formatted string with direction, amount and currency
    """
    from src.ledger import Direction, JournalLine

    line = JournalLine(
        id=uuid4(),
        journal_entry_id=uuid4(),
        account_id=uuid4(),
        direction=Direction.DEBIT,
        amount="1000.00",
        currency="USD",
    )
    result = repr(line)
    assert result == "<JournalLine DEBIT 1000.00 USD>"


def test_uploaded_document_repr():
    """
    GIVEN an UploadedDocument instance
    WHEN calling repr() on it
    THEN it returns a formatted string with filename and document type
    """
    from src.extraction import DocumentType, UploadedDocument

    document = UploadedDocument(
        id=uuid4(),
        user_id=uuid4(),
        original_filename="statement.pdf",
        document_type=DocumentType.BANK_STATEMENT,
        file_path="uploads/statement.pdf",
        file_hash="abc123",
    )
    result = repr(document)
    # DocumentType.BANK_STATEMENT.value = "bank_statement" (lowercase with underscore)
    assert result == "<UploadedDocument statement.pdf (bank_statement)>"


def test_atomic_transaction_repr():
    """
    GIVEN an AtomicTransaction instance
    WHEN calling repr() on it
    THEN it returns a formatted string with date, direction, amount and currency
    """
    from src.models.layer2 import AtomicTransaction, TransactionDirection

    transaction = AtomicTransaction(
        id=uuid4(),
        user_id=uuid4(),
        txn_date=date(2024, 1, 15),
        direction=TransactionDirection.IN,
        amount="500.00",
        currency="SGD",
        description="Test transaction",
    )
    result = repr(transaction)
    assert result == "<AtomicTransaction 2024-01-15 IN 500.00 SGD>"


def test_atomic_position_repr():
    """
    GIVEN an AtomicPosition instance
    WHEN calling repr() on it
    THEN it returns a formatted string with date, asset, quantity, value and currency
    """
    from src.models.layer2 import AtomicPosition

    position = AtomicPosition(
        id=uuid4(),
        user_id=uuid4(),
        snapshot_date=date(2024, 1, 15),
        asset_identifier="AAPL",
        quantity="100",
        market_value="15000.00",
        currency="USD",
    )
    result = repr(position)
    assert result == "<AtomicPosition 2024-01-15 AAPL 100 @ 15000.00 USD>"


def test_dividend_income_repr():
    """
    GIVEN a DividendIncome instance
    WHEN calling repr() on it
    THEN it returns a formatted string with payment date, amount, and currency
    """
    from src.portfolio import DividendIncome

    dividend = DividendIncome(
        payment_date=date(2024, 3, 15),
        amount="125.50",
        currency="USD",
    )
    result = repr(dividend)
    assert result == "<DividendIncome 2024-03-15 125.50 USD>"


def test_market_data_override_repr():
    """
    GIVEN a MarketDataOverride instance
    WHEN calling repr() on it
    THEN it returns a formatted string with asset identifier, price, and date
    """
    from src.pricing import MarketDataOverride

    override = MarketDataOverride(
        asset_identifier="AAPL",
        price="185.50",
        price_date=date(2024, 3, 15),
    )
    result = repr(override)
    assert result == "<MarketDataOverride AAPL 185.50 on 2024-03-15>"

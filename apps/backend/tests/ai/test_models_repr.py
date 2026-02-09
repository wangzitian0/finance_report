from datetime import date
from decimal import Decimal
from uuid import uuid4

from src.models.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus
from src.models.market_data import FxRate


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


def test_openrouter_model_normalize_entry():
    """AC6.11.1: OpenRouter model normalize entry extracts modalities."""
    from src.services.openrouter_models import normalize_model_entry

    entry = {
        "id": "test/model",
        "name": "Test Model",
        "pricing": {"prompt": "0", "completion": "0.001"},
        "architecture": {"input_modalities": ["text", "image"]},
    }

    normalized = normalize_model_entry(entry)
    assert normalized["id"] == "test/model"
    assert normalized["is_free"] is False
    assert "text" in normalized["input_modalities"]
    assert "image" in normalized["input_modalities"]


def test_openrouter_model_matches_modality():
    """AC6.11.1: OpenRouter model matches modality filtering."""
    from src.services.openrouter_models import model_matches_modality

    text_model = {"input_modalities": ["text"]}
    vision_model = {"input_modalities": ["text", "image"]}

    assert model_matches_modality(text_model, "text") is True
    assert model_matches_modality(text_model, "image") is False
    assert model_matches_modality(vision_model, "image") is True
    assert model_matches_modality(vision_model, None) is True


def test_validation_route_by_threshold():
    from src.models.statement import BankStatementStatus
    from src.services.validation import route_by_threshold

    assert route_by_threshold(85, True) == BankStatementStatus.PARSED
    assert route_by_threshold(60, True) == BankStatementStatus.PARSED
    assert route_by_threshold(50, False) == BankStatementStatus.UPLOADED
    assert route_by_threshold(50, True) == BankStatementStatus.UPLOADED


def test_to_decimal():
    """AC6.11.1: Decimal conversion utility handles valid and invalid inputs."""
    from decimal import Decimal

    from src.services.openrouter_models import _to_decimal

    assert _to_decimal("1.5") == Decimal("1.5")
    assert _to_decimal("0") == Decimal("0")
    assert _to_decimal("invalid") is None
    assert _to_decimal(None) is None


def test_openrouter_normalize_model_is_free():
    """AC6.11.1: Free model identification via pricing fields."""
    from src.services.openrouter_models import normalize_model_entry

    free_model = {"id": "free/model", "name": "Free", "pricing": {"prompt": "0", "completion": "0"}}

    paid_model = {
        "id": "paid/model",
        "name": "Paid",
        "pricing": {"prompt": "0.001", "completion": "0"},
    }

    assert normalize_model_entry(free_model)["is_free"] is True
    assert normalize_model_entry(paid_model)["is_free"] is False


def test_openrouter_normalize_model_without_id():
    """AC6.11.1: Model normalization handles missing ID."""
    from src.services.openrouter_models import normalize_model_entry

    model_no_id = {"name": "No ID Model", "pricing": {"prompt": "0", "completion": "0"}}

    normalized = normalize_model_entry(model_no_id)
    assert "id" not in normalized or normalized.get("id") is None


def test_validation_confidence_with_invalid_amount():
    from src.services.validation import compute_confidence_score

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
    from src.models.account import Account, AccountType

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
    from src.models.journal import JournalEntry, JournalEntryStatus

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
    from src.models.journal import Direction, JournalLine

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
    from src.models.layer1 import DocumentType, UploadedDocument

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

import pytest
from uuid import uuid4
from datetime import date, datetime, UTC
from decimal import Decimal

from src.models.chat import ChatSession, ChatMessage, ChatMessageRole, ChatSessionStatus
from src.models.market_data import FxRate


def test_chat_session_repr():
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
    from src.services.openrouter_models import model_matches_modality

    text_model = {"input_modalities": ["text"]}
    vision_model = {"input_modalities": ["text", "image"]}

    assert model_matches_modality(text_model, "text") is True
    assert model_matches_modality(text_model, "image") is False
    assert model_matches_modality(vision_model, "image") is True
    assert model_matches_modality(vision_model, None) is True


def test_validation_route_by_threshold():
    from src.services.validation import route_by_threshold
    from src.models.statement import BankStatementStatus

    assert route_by_threshold(85, True) == BankStatementStatus.PARSED
    assert route_by_threshold(60, True) == BankStatementStatus.PARSED
    assert route_by_threshold(50, False) == BankStatementStatus.UPLOADED
    assert route_by_threshold(50, True) == BankStatementStatus.UPLOADED


def test_fx_service_to_float():
    from src.services.openrouter_models import _to_float

    assert _to_float("1.5") == 1.5
    assert _to_float("0") == 0.0
    assert _to_float("invalid") is None
    assert _to_float(None) is None


def test_openrouter_normalize_model_is_free():
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

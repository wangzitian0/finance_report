from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.models.layer3 import PositionStatus
from src.schemas.assets import (
    DepreciationResponse,
    ManagedPositionResponse,
    ReconcilePositionsResponse,
)
from src.schemas.base import BaseResponse, ListResponse
from src.schemas.chat import (
    ChatHistoryResponse,
    ChatMessagePreview,
    ChatMessageResponse,
    ChatMessageRoleEnum,
    ChatRequest,
    ChatSessionResponse,
    ChatSessionStatusEnum,
    ChatSuggestionsResponse,
)
from src.schemas.ping import PingStateResponse


class TestBaseSchemas:
    def test_base_response_config(self):
        assert BaseResponse.model_config.get("from_attributes") is True

    def test_list_response_valid(self):
        response = ListResponse(items=[1, 2, 3], total=3)
        assert response.items == [1, 2, 3]
        assert response.total == 3

    def test_list_response_empty(self):
        response = ListResponse(items=[], total=0)
        assert response.items == []
        assert response.total == 0

    def test_list_response_generic_type(self):
        response = ListResponse[str](items=["a", "b"], total=2)
        assert response.items == ["a", "b"]
        assert response.total == 2


class TestAssetsSchemas:
    def test_managed_position_response_valid(self):
        position_id = uuid4()
        user_id = uuid4()
        account_id = uuid4()

        position = ManagedPositionResponse(
            id=position_id,
            user_id=user_id,
            account_id=account_id,
            asset_identifier="AAPL",
            quantity=Decimal("100.500000"),
            cost_basis=Decimal("150.25"),
            acquisition_date=date(2024, 1, 15),
            status=PositionStatus.ACTIVE,
            currency="USD",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert position.asset_identifier == "AAPL"
        assert position.quantity == Decimal("100.500000")
        assert position.status == PositionStatus.ACTIVE

    def test_managed_position_with_optional_fields(self):
        position = ManagedPositionResponse(
            id=uuid4(),
            user_id=uuid4(),
            account_id=uuid4(),
            asset_identifier="GOOGL",
            quantity=Decimal("50"),
            cost_basis=Decimal("100"),
            acquisition_date=date(2024, 1, 1),
            disposal_date=date(2024, 12, 31),
            status=PositionStatus.DISPOSED,
            currency="USD",
            position_metadata={"notes": "test"},
            account_name="Trading Account",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert position.disposal_date == date(2024, 12, 31)
        assert position.position_metadata == {"notes": "test"}
        assert position.account_name == "Trading Account"

    def test_reconcile_positions_response_valid(self):
        response = ReconcilePositionsResponse(
            message="Reconciliation complete",
            created=5,
            updated=3,
            disposed=1,
        )
        assert response.message == "Reconciliation complete"
        assert response.created == 5
        assert response.updated == 3
        assert response.disposed == 1
        assert response.skipped == 0
        assert response.skipped_assets == []

    def test_reconcile_positions_with_skipped(self):
        response = ReconcilePositionsResponse(
            message="Partial reconciliation",
            created=2,
            updated=1,
            disposed=0,
            skipped=3,
            skipped_assets=["UNKNOWN1", "UNKNOWN2", "UNKNOWN3"],
        )
        assert response.skipped == 3
        assert len(response.skipped_assets) == 3

    def test_reconcile_positions_negative_fails(self):
        with pytest.raises(ValidationError):
            ReconcilePositionsResponse(
                message="Invalid",
                created=-1,
                updated=0,
                disposed=0,
            )

    def test_depreciation_response_valid(self):
        position_id = uuid4()
        response = DepreciationResponse(
            position_id=position_id,
            asset_identifier="EQUIPMENT-001",
            period_depreciation=Decimal("1000.00"),
            accumulated_depreciation=Decimal("5000.00"),
            book_value=Decimal("15000.00"),
            method="straight_line",
            useful_life_years=10,
            salvage_value=Decimal("2000.00"),
        )
        assert response.position_id == position_id
        assert response.method == "straight_line"
        assert response.useful_life_years == 10


class TestChatSchemas:
    def test_chat_message_role_enum_values(self):
        assert ChatMessageRoleEnum.USER == "user"
        assert ChatMessageRoleEnum.ASSISTANT == "assistant"
        assert ChatMessageRoleEnum.SYSTEM == "system"

    def test_chat_session_status_enum_values(self):
        assert ChatSessionStatusEnum.ACTIVE == "active"
        assert ChatSessionStatusEnum.DELETED == "deleted"

    def test_chat_request_valid(self):
        request = ChatRequest(message="Hello, AI!")
        assert request.message == "Hello, AI!"
        assert request.session_id is None
        assert request.model is None

    def test_chat_request_with_session_and_model(self):
        session_id = uuid4()
        request = ChatRequest(
            message="Hello",
            session_id=session_id,
            model="gemini-2.0-flash",
        )
        assert request.session_id == session_id
        assert request.model == "gemini-2.0-flash"

    def test_chat_request_empty_message_fails(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="")

    def test_chat_request_long_message_fails(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="x" * 4001)

    def test_chat_message_response_valid(self):
        message_id = uuid4()
        session_id = uuid4()

        response = ChatMessageResponse(
            id=message_id,
            session_id=session_id,
            role=ChatMessageRoleEnum.USER,
            content="Test message",
            created_at=datetime.now(),
        )
        assert response.id == message_id
        assert response.role == ChatMessageRoleEnum.USER
        assert response.tokens_in is None
        assert response.tokens_out is None

    def test_chat_message_response_with_tokens(self):
        response = ChatMessageResponse(
            id=uuid4(),
            session_id=uuid4(),
            role=ChatMessageRoleEnum.ASSISTANT,
            content="AI response",
            tokens_in=100,
            tokens_out=50,
            model_name="gemini-2.0-flash",
            created_at=datetime.now(),
        )
        assert response.tokens_in == 100
        assert response.tokens_out == 50
        assert response.model_name == "gemini-2.0-flash"

    def test_chat_message_preview_valid(self):
        preview = ChatMessagePreview(
            role=ChatMessageRoleEnum.USER,
            content="Preview content",
            created_at=datetime.now(),
        )
        assert preview.role == ChatMessageRoleEnum.USER
        assert preview.content == "Preview content"

    def test_chat_session_response_valid(self):
        session_id = uuid4()
        response = ChatSessionResponse(
            id=session_id,
            title="Test Session",
            status=ChatSessionStatusEnum.ACTIVE,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            last_active_at=datetime.now(),
        )
        assert response.id == session_id
        assert response.title == "Test Session"
        assert response.message_count == 0
        assert response.last_message is None
        assert response.messages == []

    def test_chat_session_response_with_messages(self):
        message = ChatMessageResponse(
            id=uuid4(),
            session_id=uuid4(),
            role=ChatMessageRoleEnum.USER,
            content="Test",
            created_at=datetime.now(),
        )
        preview = ChatMessagePreview(
            role=ChatMessageRoleEnum.USER,
            content="Preview",
            created_at=datetime.now(),
        )
        response = ChatSessionResponse(
            id=uuid4(),
            title="Session with messages",
            status=ChatSessionStatusEnum.ACTIVE,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            last_active_at=datetime.now(),
            message_count=1,
            last_message=preview,
            messages=[message],
        )
        assert response.message_count == 1
        assert response.last_message is not None
        assert len(response.messages) == 1

    def test_chat_history_response_valid(self):
        session = ChatSessionResponse(
            id=uuid4(),
            title="History session",
            status=ChatSessionStatusEnum.ACTIVE,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            last_active_at=datetime.now(),
        )
        response = ChatHistoryResponse(sessions=[session])
        assert len(response.sessions) == 1

    def test_chat_suggestions_response_valid(self):
        response = ChatSuggestionsResponse(suggestions=["What is my balance?", "Show recent transactions"])
        assert len(response.suggestions) == 2
        assert "What is my balance?" in response.suggestions


class TestPingSchemas:
    def test_ping_state_response_valid(self):
        response = PingStateResponse(
            state="ping",
            toggle_count=5,
            updated_at=datetime.now(),
        )
        assert response.state == "ping"
        assert response.toggle_count == 5
        assert response.updated_at is not None

    def test_ping_state_response_without_updated_at(self):
        response = PingStateResponse(
            state="pong",
            toggle_count=0,
        )
        assert response.state == "pong"
        assert response.toggle_count == 0
        assert response.updated_at is None

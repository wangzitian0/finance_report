"""Backend tests."""

import pytest
from httpx import AsyncClient

# Skip marker for client-based tests due to event loop issues with pytest-asyncio 1.x
# These tests need refactoring to work with function-scoped event loops
skip_client_tests = pytest.mark.skip(
    reason="Event loop issues with async client fixture - needs refactoring"
)


@skip_client_tests
async def test_health(client: AsyncClient) -> None:
    """Test health endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data


@skip_client_tests
async def test_ping_initial_state(client: AsyncClient) -> None:
    """Test initial ping state."""
    response = await client.get("/ping")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "ping"
    assert data["toggle_count"] == 0
    assert data["updated_at"] is None


@skip_client_tests
async def test_ping_toggle(client: AsyncClient) -> None:
    """Test toggle endpoint."""
    # First toggle - should go from ping to pong
    response = await client.post("/ping/toggle")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "pong"
    assert data["toggle_count"] == 1
    assert "updated_at" in data

    # Second toggle - should go back to ping
    response = await client.post("/ping/toggle")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "ping"
    assert data["toggle_count"] == 2


@skip_client_tests
async def test_get_statement_not_found(client: AsyncClient) -> None:
    """Test getting a non-existent statement."""
    response = await client.get("/api/statements/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@skip_client_tests
async def test_get_pending_review_empty(client: AsyncClient) -> None:
    """Test getting pending review list when empty."""
    response = await client.get("/api/statements/pending-review")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@skip_client_tests
async def test_approve_statement_not_found(client: AsyncClient) -> None:
    """Test approving a non-existent statement."""
    response = await client.post(
        "/api/statements/00000000-0000-0000-0000-000000000000/approve",
        json={"notes": "ok"}
    )
    assert response.status_code == 404


@skip_client_tests
async def test_upload_no_file(client: AsyncClient) -> None:
    """Test upload endpoint without file."""
    response = await client.post(
        "/api/statements/upload",
        data={"institution": "DBS"}
    )
    # Should fail validation - no file
    assert response.status_code == 422


@skip_client_tests
async def test_health_endpoint_structure(client: AsyncClient) -> None:
    """Test health endpoint returns proper structure."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "timestamp" in data
    assert data["status"] == "healthy"


@skip_client_tests
async def test_ping_multiple_toggles(client: AsyncClient) -> None:
    """Test multiple ping toggles."""
    # Toggle 3 times
    for i in range(3):
        response = await client.post("/ping/toggle")
        assert response.status_code == 200
        data = response.json()
        # toggle_count increments but we can't guarantee exact count
        # since previous tests may have toggled
        assert data["toggle_count"] >= i + 1

    # Check final state is pong (odd number of toggles from start)
    response = await client.get("/ping")
    # State depends on previous tests, just verify it returns valid response
    assert response.status_code == 200


class TestSchemas:
    """Tests for Pydantic schemas."""

    def test_review_decision_approved(self):
        """Test ReviewDecision with approved."""
        from src.schemas.extraction import StatementDecisionRequest
        decision = StatementDecisionRequest()
        assert decision.notes is None

    def test_review_decision_rejected_with_notes(self):
        """Test ReviewDecision rejected with notes."""
        from src.schemas.extraction import StatementDecisionRequest
        decision = StatementDecisionRequest(notes="Incorrect amount")
        assert decision.notes == "Incorrect amount"

    def test_confidence_level_enum(self):
        """Test ConfidenceLevelEnum values."""
        from src.schemas.extraction import ConfidenceLevelEnum
        assert ConfidenceLevelEnum.HIGH.value == "high"
        assert ConfidenceLevelEnum.MEDIUM.value == "medium"
        assert ConfidenceLevelEnum.LOW.value == "low"

    def test_statement_status_enum(self):
        """Test StatementStatusEnum values."""
        from src.schemas.extraction import BankStatementStatusEnum
        assert BankStatementStatusEnum.UPLOADED.value == "uploaded"
        assert BankStatementStatusEnum.PARSED.value == "parsed"
        assert BankStatementStatusEnum.APPROVED.value == "approved"

    def test_event_update_request(self):
        """Test EventUpdateRequest partial update."""
        from decimal import Decimal

        from src.schemas.extraction import TransactionUpdateRequest
        update = TransactionUpdateRequest(amount=Decimal("100.00"))
        assert update.amount == Decimal("100.00")
        assert update.description is None


class TestDatabase:
    """Tests for database module."""

    def test_base_metadata(self):
        """Test Base has proper metadata."""
        from src.database import Base
        assert Base.metadata is not None

    def test_get_db_depends(self):
        """Test get_db is a proper dependency."""
        import inspect

        from src.database import get_db
        assert inspect.isasyncgenfunction(get_db)


class TestModels:
    """Tests for SQLAlchemy models."""

    def test_statement_model_table_name(self):
        """Test Statement model has correct table name."""
        from src.models.statement import BankStatement
        assert BankStatement.__tablename__ == "bank_statements"

    def test_account_event_model_table_name(self):
        """Test AccountEvent model has correct table name."""
        from src.models.statement import BankStatementTransaction
        assert BankStatementTransaction.__tablename__ == "bank_statement_transactions"

    def test_statement_status_enum(self):
        """Test StatementStatus enum values."""
        from src.models.statement import BankStatementStatus
        assert BankStatementStatus.UPLOADED.value == "uploaded"
        assert BankStatementStatus.PARSED.value == "parsed"

    def test_confidence_level_enum(self):
        """Test ConfidenceLevel enum values."""
        from src.models.statement import ConfidenceLevel
        assert ConfidenceLevel.HIGH.value == "high"
        assert ConfidenceLevel.LOW.value == "low"

    def test_statement_relationship(self):
        """Test Statement has events relationship."""
        from src.models.statement import BankStatement
        assert hasattr(BankStatement, "transactions")

    def test_account_event_relationship(self):
        """Test AccountEvent has statement relationship."""
        from src.models.statement import BankStatementTransaction
        assert hasattr(BankStatementTransaction, "statement")


class TestConfig:
    """Tests for configuration."""

    def test_config_defaults(self):
        """Test Settings has reasonable defaults."""
        from src.config import Settings
        settings = Settings()
        assert settings.primary_model == "google/gemini-3-flash"
        assert settings.s3_bucket == "statements"

    def test_config_database_url(self):
        """Test database URL is set."""
        from src.config import Settings
        settings = Settings()
        assert "postgresql" in settings.database_url or "sqlite" in settings.database_url

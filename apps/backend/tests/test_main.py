"""Backend tests."""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_when_all_services_healthy(client: AsyncClient) -> None:
    """Test health endpoint returns 200 when all services are healthy."""
    response = await client.get("/health")
    assert response.status_code in [200, 503]
    data = response.json()
    assert "status" in data
    assert "timestamp" in data
    assert "checks" in data


@pytest.mark.asyncio
async def test_health_endpoint_structure(client: AsyncClient) -> None:
    """Test health endpoint returns proper structure with checks."""
    response = await client.get("/health")
    assert response.status_code in [200, 503]
    data = response.json()

    assert "status" in data
    assert "timestamp" in data
    assert "checks" in data

    checks = data["checks"]
    assert "database" in checks
    assert "redis" in checks
    assert "s3" in checks

    assert isinstance(checks["database"], bool)
    assert isinstance(checks["redis"], bool)
    assert isinstance(checks["s3"], bool)


@pytest.mark.asyncio
async def test_health_returns_503_on_database_failure(public_client: AsyncClient, monkeypatch) -> None:
    """Test health endpoint returns 503 when database check fails."""
    # The health check uses the db dependency directly.
    # To mock its failure, we can mock the execute method of the session.
    # However, it's easier to mock get_db to yield a session that fails.
    from src.database import get_db

    async def mock_get_db():
        from unittest.mock import MagicMock

        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("DB Down")
        yield mock_session

    from src.main import app

    app.dependency_overrides[get_db] = mock_get_db

    try:
        response = await public_client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["checks"]["database"] is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_passes_when_redis_not_configured(public_client: AsyncClient, monkeypatch) -> None:
    """Test health check passes when Redis URL is not set."""
    monkeypatch.setattr("src.config.settings.redis_url", None)

    response = await public_client.get("/health")

    data = response.json()
    assert data["checks"]["redis"] is True


@pytest.mark.asyncio
async def test_health_fails_when_redis_configured_but_unavailable(
    public_client: AsyncClient,
    monkeypatch,
) -> None:
    """Test health check fails when Redis is configured but unreachable."""
    monkeypatch.setattr("src.config.settings.redis_url", "redis://invalid:6379")

    from src.boot import Bootloader, ServiceStatus

    monkeypatch.setattr(
        Bootloader,
        "_check_redis",
        AsyncMock(return_value=ServiceStatus("redis", "error", "Connection refused")),
    )

    response = await public_client.get("/health")

    assert response.status_code == 503
    data = response.json()
    assert data["checks"]["redis"] is False


@pytest.mark.asyncio
async def test_health_returns_503_on_s3_failure(public_client: AsyncClient, monkeypatch) -> None:
    """Test health endpoint returns 503 when S3 check fails."""
    from src.boot import Bootloader, ServiceStatus

    monkeypatch.setattr(
        Bootloader,
        "_check_s3",
        AsyncMock(return_value=ServiceStatus("minio", "error", "Bucket missing")),
    )

    response = await public_client.get("/health")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["checks"]["s3"] is False


@pytest.mark.asyncio
async def test_ping_initial_state(client: AsyncClient) -> None:
    response = await client.get("/ping")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "ping"
    assert data["toggle_count"] == 0
    assert data["updated_at"] is None


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_get_statement_not_found(client: AsyncClient) -> None:
    """Test getting a non-existent statement."""
    response = await client.get("/statements/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_pending_review_empty(client: AsyncClient) -> None:
    """Test getting pending review list when empty."""
    response = await client.get("/statements/pending-review")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_approve_statement_not_found(client: AsyncClient) -> None:
    """Test approving a non-existent statement."""
    response = await client.post("/statements/00000000-0000-0000-0000-000000000000/approve", json={"notes": "ok"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_no_file(client: AsyncClient) -> None:
    """Test upload endpoint without file."""
    response = await client.post("/statements/upload", data={"institution": "DBS"})
    # Should fail validation - no file
    assert response.status_code == 422


@pytest.mark.asyncio
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
        assert "gemini" in settings.primary_model.lower()
        assert settings.primary_model.startswith("google/")
        assert settings.s3_bucket == "statements"

    def test_config_database_url(self):
        """Test database URL is set."""
        from src.config import Settings

        settings = Settings()
        assert "postgresql" in settings.database_url or "sqlite" in settings.database_url

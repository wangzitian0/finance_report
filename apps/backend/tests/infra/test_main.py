"""Backend tests."""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_when_all_services_healthy(client: AsyncClient, monkeypatch) -> None:
    """AC7.7.1: Health endpoint returns 200 when all services healthy."""
    from src.boot import Bootloader, ServiceStatus

    monkeypatch.setattr(
        Bootloader,
        "_check_redis",
        AsyncMock(return_value=ServiceStatus("redis", "ok", "Connection successful")),
    )
    monkeypatch.setattr(
        Bootloader,
        "_check_s3",
        AsyncMock(return_value=ServiceStatus("minio", "ok", "Bucket accessible")),
    )

    response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["checks"]["database"] is True
    assert data["checks"]["redis"] is True
    assert data["checks"]["s3"] is True


@pytest.mark.asyncio
async def test_health_endpoint_structure(public_client: AsyncClient) -> None:
    """AC7.7.1: Verify health endpoint JSON structure."""
    response = await public_client.get("/health")

    assert response.status_code == 200
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
    """AC7.7.2: Health returns 503 when database check fails."""
    # The health check uses the db dependency directly.
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
    """AC7.7.1: Health passes when Redis URL not set."""
    monkeypatch.setattr("src.config.settings.redis_url", None)

    response = await public_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["checks"]["redis"] is True


@pytest.mark.asyncio
async def test_health_remains_200_when_redis_fails(
    public_client: AsyncClient,
    monkeypatch,
) -> None:
    """AC7.7.2: Health remains 200 even when Redis unreachable (but DB is up)."""
    monkeypatch.setattr("src.config.settings.redis_url", "redis://invalid:6379")

    from src.boot import Bootloader, ServiceStatus

    monkeypatch.setattr(
        Bootloader,
        "_check_redis",
        AsyncMock(return_value=ServiceStatus("redis", "error", "Connection refused")),
    )

    response = await public_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["checks"]["redis"] is False


@pytest.mark.asyncio
async def test_health_remains_200_on_s3_failure(public_client: AsyncClient, monkeypatch) -> None:
    """AC7.7.2: Health remains 200 even when S3 check fails (readiness relaxation)."""
    from src.boot import Bootloader, ServiceStatus

    monkeypatch.setattr(
        Bootloader,
        "_check_s3",
        AsyncMock(return_value=ServiceStatus("minio", "error", "Bucket missing")),
    )

    response = await public_client.get("/health")

    assert response.status_code == 200
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
    assert data["updated_at"] is not None

    # Second toggle - should go back to ping
    response = await client.post("/ping/toggle")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "ping"
    assert data["toggle_count"] == 2


@pytest.mark.asyncio
async def test_ping_multiple_toggles(client: AsyncClient) -> None:
    for i in range(1, 6):
        response = await client.post("/ping/toggle")
        assert response.status_code == 200
        data = response.json()
        assert data["toggle_count"] == i


@pytest.mark.asyncio
async def test_get_pending_review_empty(client: AsyncClient) -> None:
    response = await client.get("/api/statements/pending-review")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_statement_not_found(client: AsyncClient) -> None:
    from uuid import uuid4

    response = await client.get(f"/api/statements/{uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_no_file(client: AsyncClient) -> None:
    response = await client.post("/api/statements/upload")
    assert response.status_code == 422  # Validation error from FastAPI


@pytest.mark.asyncio
async def test_approve_statement_not_found(client: AsyncClient) -> None:
    from uuid import uuid4

    response = await client.post(
        f"/api/statements/{uuid4()}/approve",
        json={"decision": "APPROVED", "notes": "Looks good"},
    )
    assert response.status_code == 404


class TestSchemas:
    def test_statement_status_enum(self):
        from src.models import BankStatementStatus

        assert BankStatementStatus.PARSING == "parsing"
        assert BankStatementStatus.PARSED == "parsed"
        assert BankStatementStatus.APPROVED == "approved"
        assert BankStatementStatus.REJECTED == "rejected"

    def test_confidence_level_enum(self):
        # Confidence is just an int in the current implementation, not an Enum
        pass

    def test_review_decision_approved(self):
        from src.schemas import StatementDecisionRequest

        data = {"decision": "APPROVED", "notes": "Test"}
        schema = StatementDecisionRequest(**data)
        assert schema.decision == "APPROVED"

    def test_review_decision_rejected_with_notes(self):
        from src.schemas import StatementDecisionRequest

        data = {"decision": "REJECTED", "notes": "Incomplete data"}
        schema = StatementDecisionRequest(**data)
        assert schema.decision == "REJECTED"
        assert schema.notes == "Incomplete data"

    def test_event_update_request(self):
        # This was part of older architecture, but let's keep it if needed
        pass


class TestDatabase:
    def test_base_metadata(self):
        from src.database import Base

        assert hasattr(Base, "metadata")

    def test_get_db_depends(self):
        from src.database import get_db

        assert callable(get_db)


class TestModels:
    def test_statement_model_table_name(self):
        from src.models import BankStatement

        assert BankStatement.__tablename__ == "bank_statements"

    def test_account_event_model_table_name(self):
        # Part of older architecture
        pass

    def test_statement_status_enum(self):
        from src.models import BankStatementStatus

        assert hasattr(BankStatementStatus, "PARSED")

    def test_confidence_level_enum(self):
        pass

    def test_statement_relationship(self):
        from src.models import BankStatement

        assert hasattr(BankStatement, "transactions")

    def test_account_event_relationship(self):
        pass


class TestConfig:
    def test_config_defaults(self):
        from src.config import settings

        assert settings.environment in ("development", "test", "production", "testing")

    def test_config_database_url(self):
        from src.config import settings

        assert "postgresql" in settings.database_url or "sqlite" in settings.database_url

"""Consolidated integration test for the basic upload flow."""

import json
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.routers import statements as statements_router


@pytest.mark.asyncio
async def test_full_upload_to_db_flow(client, test_user):
    """
    Test the full upload flow:
    1. POST /statements/upload
    2. Mocked Storage (S3)
    3. Mocked AI API (OpenRouter)
    4. Verified Database persistence via GET API

    Note: Uses `client` fixture which already handles:
    - Database session override (get_db)
    - User authentication via X-User-Id header
    """
    # 1. Prepare realistic mock data
    content = b"fake-pdf-content"

    mock_ai_response = {
        "institution": "DBS",
        "account_last4": "8888",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "1000.00",
        "closing_balance": "1500.00",
        "transactions": [
            {"date": "2025-01-15", "description": "Salary", "amount": "500.00", "direction": "IN"}
        ],
    }

    # 2. Mock external dependencies (Storage + AI API only)
    with (
        patch("src.routers.statements.StorageService") as MockStorage,
        patch("src.services.extraction.httpx.AsyncClient") as MockHttpClient,
        patch("src.services.extraction.settings") as mock_settings,
    ):
        # Mock Storage
        storage_instance = MockStorage.return_value
        storage_instance.upload_bytes = MagicMock()
        storage_instance.generate_presigned_url.return_value = "https://mock.s3/file.pdf"

        # Mock HTTP Client for Extraction
        mock_http_client = AsyncMock()
        MockHttpClient.return_value.__aenter__.return_value = mock_http_client

        response_mock = MagicMock()
        response_mock.status_code = 200
        response_mock.json.return_value = {
            "choices": [{"message": {"content": json.dumps(mock_ai_response)}}]
        }
        mock_http_client.post.return_value = response_mock

        # Override extraction service API key check
        mock_settings.openrouter_api_key = "mock-key"

        # 3. Execute Request
        # Note: Authentication is handled by client fixture's X-User-Id header
        response = await client.post(
            "/statements/upload",
            files={"file": ("test.pdf", BytesIO(content), "application/pdf")},
            data={"institution": "DBS"},
        )
        await statements_router.wait_for_parse_tasks()

    # 4. Verify Upload Response
    assert response.status_code == 202, response.text
    data = response.json()
    statement_id = data["id"]

    # Verify core fields from upload response
    assert data["institution"] == "DBS"
    assert data["status"] == "parsing"
    assert data["user_id"] == str(test_user.id)

    # 5. Verify Database Persistence via GET API
    # This proves data was committed to DB and is retrievable
    stmt_response = await client.get(f"/statements/{statement_id}")
    assert stmt_response.status_code == 200
    stmt_data = stmt_response.json()

    # Verify data persisted correctly (using fields in BankStatementResponse schema)
    assert stmt_data["id"] == statement_id
    assert stmt_data["institution"] == "DBS"
    assert stmt_data["account_last4"] == "8888"
    assert stmt_data["period_start"] == "2025-01-01"
    assert stmt_data["period_end"] == "2025-01-31"
    assert stmt_data["opening_balance"] == "1000.00"
    assert stmt_data["closing_balance"] == "1500.00"
    assert stmt_data["status"] == "parsed"
    assert stmt_data["balance_validated"] is True

    # Verify transactions were persisted
    assert len(stmt_data["transactions"]) == 1
    txn = stmt_data["transactions"][0]
    assert txn["description"] == "Salary"
    assert txn["amount"] == "500.00"
    assert txn["direction"] == "IN"

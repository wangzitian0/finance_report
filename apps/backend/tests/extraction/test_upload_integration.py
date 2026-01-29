"""Consolidated integration test for the basic upload flow."""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from src.routers import statements as statements_router


async def mock_stream_generator(content: str):
    """Helper to create async generator for streaming mock."""
    yield content


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
        "transactions": [{"date": "2025-01-15", "description": "Salary", "amount": "500.00", "direction": "IN"}],
    }

    with (
        patch("src.routers.statements.StorageService") as MockStorage,
        patch("src.services.extraction.stream_openrouter_json") as mock_stream,
        patch("src.services.extraction.settings") as mock_settings,
    ):
        storage_instance = MockStorage.return_value
        storage_instance.upload_bytes = MagicMock()
        storage_instance.generate_presigned_url.return_value = "https://mock.s3/file.pdf"

        mock_stream.return_value = mock_stream_generator(json.dumps(mock_ai_response))

        mock_settings.openrouter_api_key = "mock-key"

        response = await client.post(
            "/statements/upload",
            files={"file": ("test.pdf", BytesIO(content), "application/pdf")},
            data={"institution": "DBS"},
        )
        await statements_router.wait_for_parse_tasks()

    assert response.status_code == 202, response.text
    data = response.json()
    statement_id = data["id"]

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

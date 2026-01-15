"""Consolidated integration test for the basic upload flow."""

import hashlib
import json
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.models.statement import BankStatement, BankStatementStatus
from src.services.extraction import ExtractionService


@pytest.mark.asyncio
async def test_full_upload_to_db_flow(db, test_user):
    """
    Test the full upload flow:
    1. POST /statements/upload
    2. Mocked Storage (S3)
    3. Mocked AI API (OpenRouter)
    4. Verified Database record creation
    """
    # 1. Prepare realistic mock data
    content = b"fake-pdf-content"
    file_hash = hashlib.sha256(content).hexdigest()
    
    mock_ai_response = {
        "institution": "DBS",
        "account_last4": "8888",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "1000.00",
        "closing_balance": "1500.00",
        "transactions": [
            {"date": "2025-01-15", "description": "Salary", "amount": "500.00", "direction": "IN"}
        ]
    }

    # 2. Mock external dependencies
    # Mock StorageService
    with patch("src.routers.statements.StorageService") as MockStorage:
        storage_instance = MockStorage.return_value
        storage_instance.upload_bytes = MagicMock()
        storage_instance.generate_presigned_url.return_value = "https://mock.s3/file.pdf"
        
        # Mock ExtractionService's external API call (httpx)
        with patch("src.services.extraction.httpx.AsyncClient") as MockHttpClient:
            client_instance = AsyncMock()
            MockHttpClient.return_value.__aenter__.return_value = client_instance
            
            # Ensure the service has a mock API key to pass internal check
            from src.services.extraction import ExtractionService
            original_init = ExtractionService.__init__
            def mock_init(self, *args, **kwargs):
                original_init(self, *args, **kwargs)
                self.api_key = "mock-key"
            
            with patch.object(ExtractionService, "__init__", mock_init):
                response_mock = MagicMock()
                response_mock.status_code = 200
                response_mock.json.return_value = {
                    "choices": [{"message": {"content": json.dumps(mock_ai_response)}}]
                }
                client_instance.post.return_value = response_mock

                # 3. Execute Request
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    # Need to act as the test_user
                    # Assuming conftest.py provides a way to authenticate or we bypass it for this unit-integration test
                    # Often done via dependency_overrides or a test token
                    
                    # For this test, let's use the router directly to simplify auth if needed, 
                    # or rely on the fact that 'db' and 'test_user' fixtures are provided.
                    
                    from src.auth import get_current_user_id
                    app.dependency_overrides[get_current_user_id] = lambda: test_user.id
                    
                    response = await ac.post(
                        "/statements/upload",
                        files={"file": ("test.pdf", BytesIO(content), "application/pdf")},
                        data={"institution": "DBS"},
                    )
                    
                    # Cleanup override
                    app.dependency_overrides.pop(get_current_user_id, None)

            # 4. Verify Response
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["institution"] == "DBS"
            assert data["opening_balance"] == "1000.00"
            assert data["status"] == "parsed"  # Auto-accepted due to valid balance
            assert data["balance_validated"] is True
            assert len(data["transactions"]) == 1
            
            # 5. Verify Database Persistence
            statement_id = data["id"]
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            
            stmt_result = await db.execute(
                select(BankStatement)
                .where(BankStatement.id == statement_id)
                .options(selectinload(BankStatement.transactions))
            )
            db_stmt = stmt_result.scalar_one()
            assert db_stmt.user_id == test_user.id
            assert db_stmt.file_hash == file_hash
            assert len(db_stmt.transactions) == 1
            assert db_stmt.transactions[0].description == "Salary"

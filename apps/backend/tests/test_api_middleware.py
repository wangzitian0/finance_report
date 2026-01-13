"""Tests for API middleware."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI

from src.api.middleware import add_cors_middleware, logging_middleware


def test_add_cors_middleware():
    """Test CORS middleware is added to app."""
    app = FastAPI()

    with patch("src.api.middleware.CORSMiddleware") as mock_cors:
        add_cors_middleware(app)

        # Assert that add_middleware was called
        assert app.middleware.called or len(app.middleware_stack) > 0


@pytest.mark.asyncio
async def test_logging_middleware():
    """Test logging middleware processes requests."""
    # Create mock request and call_next
    mock_request = MagicMock()
    mock_response = MagicMock()
    call_next = MagicMock(return_value=mock_response)

    # Test middleware (TODO: Add actual logging assertions when implemented)
    response = await logging_middleware(mock_request, call_next)

    assert response == mock_response
    call_next.assert_called_once_with(mock_request)

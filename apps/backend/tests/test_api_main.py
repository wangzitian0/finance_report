"""Tests for API main application."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from src.api.main import app


def test_app_creation():
    """Test that FastAPI app is created successfully."""
    assert app is not None
    assert app.title == "Finance Report API"
    assert app.version == "0.1.0"


def test_health_endpoint():
    """Test health check endpoint."""
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data


@patch("src.api.main.get_db")
def test_ping_endpoint_no_data(mock_get_db):
    """Test ping endpoint with no existing state."""
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db

    # Mock database query returning None
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    client = TestClient(app)
    response = client.get("/ping")

    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "ping"
    assert data["toggle_count"] == 0
    assert data["updated_at"] is None


def test_cors_headers():
    """Test that CORS headers are set correctly."""
    client = TestClient(app)
    response = client.options("/health")

    # Check that CORS headers are present
    assert "access-control-allow-origin" in response.headers


def test_global_exception_handler():
    """Test that global exception handler returns JSON response."""
    client = TestClient(app)

    # This should trigger the global exception handler
    response = client.get("/nonexistent-endpoint")

    # Should get 404 from FastAPI, but with JSON response format
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"

"""AC6.11: AI models catalog API router tests.

Tests all endpoints in src/routers/ai_models.py covering:
- GET /ai/models - List available AI models with filters (modality, free_only)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import status
from httpx import AsyncClient

from src.schemas.ai_models import AIModelCatalogResponse


async def test_list_models(client: AsyncClient):
    """AC6.11.1: Test listing all AI models."""
    # WHEN: List all models
    response = await client.get("/ai/models")

    # THEN: Models returned successfully
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, dict)
    assert "default_model" in data
    assert "fallback_models" in data
    assert "models" in data
    assert isinstance(data["models"], list)

    # Verify response schema
    AIModelCatalogResponse.model_validate(data)


async def test_list_models_with_modality_filter(client: AsyncClient):
    """AC6.11.2: Test filtering models by modality."""
    # WHEN: List models with modality filter
    response = await client.get("/ai/models?modality=text")

    # THEN: Models returned with modality filter
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data["models"], list)
    # Models should be filtered by modality (text models)


async def test_list_models_with_free_only_filter(client: AsyncClient):
    """AC6.11.3: Test filtering models by free_only."""
    # WHEN: List models with free_only filter
    response = await client.get("/ai/models?free_only=true")

    # THEN: Models returned with free_only filter
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data["models"], list)
    # Models should be filtered to only free models


async def test_list_models_with_both_filters(client: AsyncClient):
    """AC6.11.4: Test filtering models with both modality and free_only filters."""
    # WHEN: List models with both filters
    response = await client.get("/ai/models?modality=text&free_only=true")

    # THEN: Models returned with both filters
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data["models"], list)
    # Models should be filtered by both modality and free_only


@patch("src.routers.ai_models.fetch_model_catalog")
async def test_list_models_error_handling(mock_fetch: AsyncMock, client: AsyncClient):
    """AC6.11.5: Test error handling when model catalog is unavailable."""
    # GIVEN: fetch_model_catalog raises an exception
    mock_fetch.side_effect = Exception("Catalog service unavailable")

    # WHEN: List models
    response = await client.get("/ai/models")

    # THEN: Returns 503 Service Unavailable
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    data = response.json()
    assert "Model catalog unavailable" in data["detail"]
    assert mock_fetch.called


"""Tests for AI models router."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.routers.ai_models import list_models


@pytest.mark.asyncio
async def test_list_models_success():
    """AC6.11.1: List models endpoint returns models with default parameters."""
    mock_models = [
        {
            "id": "free/model",
            "name": "Free Model",
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text"]},
        },
        {
            "id": "paid/model",
            "name": "Paid Model",
            "pricing": {"prompt": "0.001", "completion": "0.002"},
            "architecture": {"input_modalities": ["text", "image"]},
        },
    ]

    with patch("src.routers.ai_models.fetch_model_catalog", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_models

        result = await list_models(modality=None, free_only=False)

    assert result.models is not None
    assert result.default_model is not None
    assert len(result.models) == 2


@pytest.mark.asyncio
async def test_list_models_filter_by_modality():
    """AC6.11.1: List models filters by modality."""
    mock_models = [
        {
            "id": "text/only",
            "name": "Text Only",
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text"]},
        },
        {
            "id": "vision/model",
            "name": "Vision Model",
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text", "image"]},
        },
    ]

    with patch("src.routers.ai_models.fetch_model_catalog", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_models

        result = await list_models(modality="image", free_only=False)

    assert len(result.models) == 1
    assert result.models[0].id == "vision/model"


@pytest.mark.asyncio
async def test_list_models_free_only():
    """AC6.11.1: List models filters to free-only models."""
    mock_models = [
        {
            "id": "free/model",
            "name": "Free Model",
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text"]},
        },
        {
            "id": "paid/model",
            "name": "Paid Model",
            "pricing": {"prompt": "0.001", "completion": "0.002"},
            "architecture": {"input_modalities": ["text"]},
        },
    ]

    with patch("src.routers.ai_models.fetch_model_catalog", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_models

        result = await list_models(modality=None, free_only=True)

    assert len(result.models) == 1
    assert result.models[0].id == "free/model"


@pytest.mark.asyncio
async def test_list_models_catalog_unavailable():
    """AC6.11.1: List models returns 503 when catalog unavailable."""
    with patch("src.routers.ai_models.fetch_model_catalog", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = Exception("Network error")

        with pytest.raises(HTTPException) as exc_info:
            await list_models(modality=None, free_only=False)

    assert exc_info.value.status_code == 503
    assert "unavailable" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_list_models_sorted_free_first():
    """AC6.11.1: List models sorts free models first."""
    mock_models = [
        {
            "id": "paid/model",
            "name": "Paid Model",
            "pricing": {"prompt": "0.001", "completion": "0.002"},
            "architecture": {"input_modalities": ["text"]},
        },
        {
            "id": "free/model",
            "name": "Free Model",
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text"]},
        },
    ]

    with patch("src.routers.ai_models.fetch_model_catalog", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_models

        result = await list_models(modality=None, free_only=False)

    assert result.models[0].is_free is True
    assert result.models[1].is_free is False

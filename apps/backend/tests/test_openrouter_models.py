"""Tests for OpenRouter model catalog service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.services.openrouter_models import (
    _MODEL_CACHE,
    fetch_model_catalog,
    get_model_info,
    is_model_known,
    model_matches_modality,
    normalize_model_entry,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear model cache before each test."""
    _MODEL_CACHE["models"] = []
    _MODEL_CACHE["expires_at"] = 0.0
    yield
    _MODEL_CACHE["models"] = []
    _MODEL_CACHE["expires_at"] = 0.0


def test_normalize_model_entry_free_model():
    """Free models should be identified correctly."""
    entry = {
        "id": "test/model",
        "name": "Test Model",
        "pricing": {"prompt": "0", "completion": "0"},
        "architecture": {"input_modalities": ["text", "image"]},
    }
    result = normalize_model_entry(entry)
    assert result["id"] == "test/model"
    assert result["name"] == "Test Model"
    assert result["is_free"] is True
    assert result["input_modalities"] == ["text", "image"]


def test_normalize_model_entry_paid_model():
    """Paid models should be identified correctly."""
    entry = {
        "id": "paid/model",
        "name": "Paid Model",
        "pricing": {"prompt": "0.001", "completion": "0.002"},
        "architecture": {"input_modalities": ["text"]},
    }
    result = normalize_model_entry(entry)
    assert result["is_free"] is False


def test_normalize_model_entry_missing_fields():
    """Missing fields should be handled gracefully."""
    entry = {"id": "minimal/model"}
    result = normalize_model_entry(entry)
    assert result["id"] == "minimal/model"
    assert result["name"] is None
    assert result["is_free"] is False
    assert result["input_modalities"] == []


def test_model_matches_modality_no_filter():
    """No filter should match all models."""
    model = {"input_modalities": ["text"]}
    assert model_matches_modality(model, None) is True


def test_model_matches_modality_matching():
    """Matching modality should return True."""
    model = {"input_modalities": ["text", "image"]}
    assert model_matches_modality(model, "image") is True


def test_model_matches_modality_not_matching():
    """Non-matching modality should return False."""
    model = {"input_modalities": ["text"]}
    assert model_matches_modality(model, "image") is False


@pytest.mark.asyncio
async def test_fetch_model_catalog_success():
    """Successful catalog fetch should return models."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{"id": "model1"}, {"id": "model2"}]}
    mock_response.raise_for_status = MagicMock()

    with patch("src.services.openrouter_models.httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.get.return_value = mock_response
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_client.return_value = mock_instance

        models = await fetch_model_catalog()

    assert len(models) == 2
    assert models[0]["id"] == "model1"


@pytest.mark.asyncio
async def test_fetch_model_catalog_caching():
    """Catalog should be cached and reused."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{"id": "cached"}]}
    mock_response.raise_for_status = MagicMock()

    with patch("src.services.openrouter_models.httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.get.return_value = mock_response
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_client.return_value = mock_instance

        # First call - should fetch
        models1 = await fetch_model_catalog()
        # Second call - should use cache
        models2 = await fetch_model_catalog()

    # Should only call API once
    assert mock_instance.get.call_count == 1
    assert models1 == models2


@pytest.mark.asyncio
async def test_fetch_model_catalog_force_refresh():
    """force_refresh should bypass cache."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{"id": "new-data"}]}
    mock_response.raise_for_status = MagicMock()

    with patch("src.services.openrouter_models.httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.get.return_value = mock_response
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_client.return_value = mock_instance

        _MODEL_CACHE["models"] = [{"id": "cached"}]
        _MODEL_CACHE["expires_at"] = float("inf")

        models = await fetch_model_catalog(force_refresh=True)

    assert mock_instance.get.call_count == 1
    assert len(models) == 1
    assert models[0]["id"] == "new-data"


@pytest.mark.asyncio
async def test_fetch_model_catalog_http_error():
    """HTTP errors during fetch should be raised."""
    with patch("src.services.openrouter_models.httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.get.side_effect = httpx.RequestError("test error")
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_client.return_value = mock_instance

        with pytest.raises(httpx.RequestError):
            await fetch_model_catalog()


@pytest.mark.asyncio
async def test_is_model_known_found():
    """Known model should return True."""
    _MODEL_CACHE["models"] = [{"id": "known/model"}]
    _MODEL_CACHE["expires_at"] = float("inf")

    result = await is_model_known("known/model")
    assert result is True


@pytest.mark.asyncio
async def test_is_model_known_not_found():
    """Unknown model should return False."""
    _MODEL_CACHE["models"] = [{"id": "other/model"}]
    _MODEL_CACHE["expires_at"] = float("inf")

    result = await is_model_known("unknown/model")
    assert result is False


@pytest.mark.asyncio
async def test_get_model_info_found():
    """Should return normalized info for a known model."""
    _MODEL_CACHE["models"] = [{"id": "known/model", "name": "Known Model"}]
    _MODEL_CACHE["expires_at"] = float("inf")

    info = await get_model_info("known/model")
    assert info is not None
    assert info["id"] == "known/model"
    assert info["name"] == "Known Model"


@pytest.mark.asyncio
async def test_get_model_info_not_found():
    """Should return None for an unknown model."""
    _MODEL_CACHE["models"] = [{"id": "other/model"}]
    _MODEL_CACHE["expires_at"] = float("inf")

    info = await get_model_info("unknown/model")
    assert info is None


@pytest.mark.asyncio
async def test_get_model_info_fetch_error():
    """Should return None if fetching the catalog fails."""
    with patch("src.services.openrouter_models.httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.get.side_effect = httpx.RequestError("test error")
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_client.return_value = mock_instance

        info = await get_model_info("any/model")
    assert info is None

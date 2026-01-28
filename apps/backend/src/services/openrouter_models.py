"""OpenRouter model catalog with lightweight caching."""

from __future__ import annotations

import asyncio
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from src.config import settings
from src.logger import get_logger


class ModelCatalogError(Exception):
    """Raised when the OpenRouter model catalog cannot be fetched."""


logger = get_logger(__name__)

_CACHE_TTL_SECONDS = 600
_MODEL_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "models": [],
}
_CACHE_LOCK = threading.Lock()


async def fetch_model_catalog(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Fetch OpenRouter model list with a short-lived cache."""
    now = time.time()
    if not force_refresh and _MODEL_CACHE["models"] and now < _MODEL_CACHE["expires_at"]:
        return list(_MODEL_CACHE["models"])

    await asyncio.to_thread(_CACHE_LOCK.acquire)
    try:
        now = time.time()
        if not force_refresh and _MODEL_CACHE["models"] and now < _MODEL_CACHE["expires_at"]:
            return list(_MODEL_CACHE["models"])

        headers = {}
        if settings.openrouter_api_key:
            headers["Authorization"] = f"Bearer {settings.openrouter_api_key}"

        timeout = httpx.Timeout(10.0, connect=5.0, read=10.0)
        start_time = time.perf_counter()

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{settings.openrouter_base_url}/models", headers=headers)
            response.raise_for_status()
            payload = response.json()

        duration_ms = (time.perf_counter() - start_time) * 1000
        models = payload.get("data", []) if isinstance(payload, dict) else []
        _MODEL_CACHE["models"] = models
        _MODEL_CACHE["expires_at"] = time.time() + _CACHE_TTL_SECONDS

        logger.info(
            "Fetched OpenRouter model catalog",
            model_count=len(models),
            duration_ms=round(duration_ms, 2),
            cache_ttl_seconds=_CACHE_TTL_SECONDS,
        )

        return list(models)
    finally:
        _CACHE_LOCK.release()


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return None


def normalize_model_entry(model: dict[str, Any]) -> dict[str, Any]:
    """Normalize raw OpenRouter model metadata to a UI-friendly shape."""
    pricing = model.get("pricing") or {}
    prompt = _to_decimal(pricing.get("prompt"))
    completion = _to_decimal(pricing.get("completion"))
    is_free = prompt == Decimal("0") and completion == Decimal("0")
    modalities = model.get("architecture", {}).get("input_modalities") or []

    return {
        "id": model.get("id"),
        "name": model.get("name"),
        "is_free": is_free,
        "input_modalities": modalities,
        "pricing": pricing,
    }


def model_matches_modality(model: dict[str, Any], modality: str | None) -> bool:
    if not modality:
        return True
    modalities = model.get("input_modalities") or []
    return modality in modalities


async def is_model_known(model_id: str) -> bool:
    """Check if a model id is present in the OpenRouter catalog."""
    models = await fetch_model_catalog()
    return any(m.get("id") == model_id for m in models)


async def get_model_info(model_id: str) -> dict[str, Any] | None:
    """Return normalized model info for a model id if available."""
    try:
        models = await fetch_model_catalog()
    except httpx.HTTPError as exc:
        logger.warning(
            "Failed to fetch model catalog for model info lookup",
            model_id=model_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise ModelCatalogError("Model catalog unavailable") from exc
    for model in models:
        if model.get("id") == model_id:
            return normalize_model_entry(model)
    return None

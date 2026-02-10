"""OpenRouter model catalog with lightweight caching."""

from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from src.config import settings
from src.logger import get_logger


class ModelCatalogError(Exception):
    """Raised when the OpenRouter model catalog cannot be fetched."""


logger = get_logger(__name__)

_CACHE_TTL_SECONDS = 600
_MAX_CACHE_ENTRIES = 10


class LRUCache:
    def __init__(self, maxsize: int = 10):
        self.cache: OrderedDict[str, Any] = OrderedDict()
        self.maxsize = maxsize
        self.lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            return None

    def set(self, key: str, value: Any) -> None:
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = value
            if len(self.cache) > self.maxsize:
                self.cache.popitem(last=False)


_MODEL_CACHE = LRUCache(maxsize=_MAX_CACHE_ENTRIES)


async def fetch_model_catalog(force_refresh: bool = False) -> list[dict[str, Any]]:
    cache_key = "model_catalog"
    now = time.time()

    cached = _MODEL_CACHE.get(cache_key)
    if not force_refresh and cached and now < cached.get("expires_at", 0):
        cache_age_seconds = round(now - (cached["expires_at"] - _CACHE_TTL_SECONDS), 1)
        logger.debug(
            "Using cached model catalog",
            model_count=len(cached["models"]),
            cache_age_seconds=cache_age_seconds,
            ttl_remaining=round(cached["expires_at"] - now, 1),
        )
        return list(cached["models"])

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

    cache_entry = {
        "models": models,
        "expires_at": time.time() + _CACHE_TTL_SECONDS,
    }
    _MODEL_CACHE.set(cache_key, cache_entry)

    logger.info(
        "Fetched OpenRouter model catalog",
        model_count=len(models),
        duration_ms=round(duration_ms, 2),
        cache_ttl_seconds=_CACHE_TTL_SECONDS,
    )

    return list(models)


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
    logger.debug("Looking up model info", model_id=model_id)

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
            normalized = normalize_model_entry(model)
            logger.info(
                "Model info found",
                model_id=model_id,
                model_name=normalized.get("name"),
                is_free=normalized.get("is_free"),
                modalities=normalized.get("input_modalities"),
            )
            return normalized

    logger.warning(
        "Model not found in catalog",
        model_id=model_id,
        catalog_size=len(models),
    )
    return None

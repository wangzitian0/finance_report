"""AI provider model catalog with lightweight caching.

The module name is kept for compatibility with existing imports. Runtime
behavior is provider-neutral and defaults to configured GLM/Z.AI models.
"""

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
    """Raised when the AI provider model catalog cannot be fetched."""


logger = get_logger(__name__)

_CACHE_TTL_SECONDS = 600
_MODEL_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "models": [],
}
_CACHE_LOCK = threading.Lock()


async def fetch_model_catalog(force_refresh: bool = False) -> list[dict[str, Any]]:
    now = time.time()
    if not force_refresh and _MODEL_CACHE["models"] and now < _MODEL_CACHE["expires_at"]:
        cache_age_seconds = round(now - (_MODEL_CACHE["expires_at"] - _CACHE_TTL_SECONDS), 1)
        logger.debug(
            "Using cached model catalog",
            model_count=len(_MODEL_CACHE["models"]),
            cache_age_seconds=cache_age_seconds,
            ttl_remaining=round(_MODEL_CACHE["expires_at"] - now, 1),
        )
        return list(_MODEL_CACHE["models"])

    await asyncio.to_thread(_CACHE_LOCK.acquire)
    try:
        now = time.time()
        if not force_refresh and _MODEL_CACHE["models"] and now < _MODEL_CACHE["expires_at"]:
            return list(_MODEL_CACHE["models"])

        if settings.ai_model_catalog_source == "configured":
            models = _configured_model_catalog()
            _MODEL_CACHE["models"] = models
            _MODEL_CACHE["expires_at"] = time.time() + _CACHE_TTL_SECONDS
            logger.info(
                "Loaded configured AI model catalog",
                provider=settings.ai_provider,
                model_count=len(models),
                cache_ttl_seconds=_CACHE_TTL_SECONDS,
            )
            return list(models)

        headers = {}
        if settings.ai_api_key:
            headers["Authorization"] = f"Bearer {settings.ai_api_key}"

        timeout = httpx.Timeout(10.0, connect=5.0, read=10.0)
        start_time = time.perf_counter()
        catalog_url = f"{settings.ai_base_url.rstrip('/')}/models"

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(catalog_url, headers=headers)
            response.raise_for_status()
            payload = response.json()

        duration_ms = (time.perf_counter() - start_time) * 1000
        models = payload.get("data", []) if isinstance(payload, dict) else []
        _MODEL_CACHE["models"] = models
        _MODEL_CACHE["expires_at"] = time.time() + _CACHE_TTL_SECONDS

        logger.info(
            "Fetched AI provider model catalog",
            provider=settings.ai_provider,
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


def _configured_model_catalog() -> list[dict[str, Any]]:
    """Build a local catalog from configured model env vars.

    Z.AI does not need a remote `/models` catalog for validation. Keeping
    the catalog local makes CI/prod deterministic and lets model swaps happen by
    changing env vars only.
    """
    entries: list[tuple[str, str, list[str]]] = [
        (settings.primary_model, "Primary chat/extraction model", ["text"]),
        (settings.ocr_model, "Dedicated OCR/layout parsing model", ["image", "pdf", "file"]),
        (settings.vision_model, "Vision fallback model", ["text", "image", "pdf", "file"]),
    ]
    entries.extend((model, "Fallback chat model", ["text"]) for model in settings.fallback_models)

    catalog: list[dict[str, Any]] = []
    seen: set[str] = set()
    for model_id, name, modalities in entries:
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        catalog.append(
            {
                "id": model_id,
                "name": name,
                "pricing": {},
                "architecture": {"input_modalities": modalities},
            }
        )
    return catalog


def normalize_model_entry(model: dict[str, Any]) -> dict[str, Any]:
    """Normalize raw provider model metadata to a UI-friendly shape."""
    pricing = model.get("pricing") or {}
    prompt = _to_decimal(pricing.get("prompt"))
    completion = _to_decimal(pricing.get("completion"))
    is_free = prompt == Decimal("0") and completion == Decimal("0")
    modalities = model.get("input_modalities") or model.get("architecture", {}).get("input_modalities") or []

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
    """Check if a model id is present in the AI provider catalog."""
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

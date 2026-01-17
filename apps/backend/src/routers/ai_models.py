"""AI model catalog endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.config import settings
from src.services.openrouter_models import (
    fetch_model_catalog,
    model_matches_modality,
    normalize_model_entry,
)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/models")
async def list_models(
    modality: str | None = Query(default=None, description="Filter by modality"),
    free_only: bool = Query(default=False, description="Return only free models"),
) -> dict[str, object]:
    """Return OpenRouter models for UI selection."""
    try:
        models = await fetch_model_catalog()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Model catalog unavailable") from exc

    normalized = [normalize_model_entry(m) for m in models]
    filtered = []
    for model in normalized:
        if not model.get("id"):
            continue
        if not model_matches_modality(model, modality):
            continue
        if free_only and not model.get("is_free"):
            continue
        filtered.append(model)

    filtered.sort(key=lambda m: (not m.get("is_free", False), m.get("name") or m.get("id")))

    return {
        "default_model": settings.primary_model,
        "fallback_models": settings.fallback_models,
        "models": filtered,
    }

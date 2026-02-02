from __future__ import annotations

from fastapi import APIRouter, Query

from src.config import settings
from src.logger import get_logger
from src.schemas.ai_models import AIModel, AIModelCatalogResponse
from src.services.openrouter_models import (
    fetch_model_catalog,
    model_matches_modality,
    normalize_model_entry,
)
from src.utils import raise_service_unavailable

router = APIRouter(prefix="/ai", tags=["ai"])
logger = get_logger(__name__)


@router.get("/models", response_model=AIModelCatalogResponse)
async def list_models(
    modality: str | None = Query(default=None, description="Filter by modality"),
    free_only: bool = Query(default=False, description="Return only free models"),
) -> AIModelCatalogResponse:
    logger.info(
        "AI model catalog requested",
        modality_filter=modality,
        free_only=free_only,
    )

    try:
        models = await fetch_model_catalog()
    except Exception as exc:
        logger.error(
            "Failed to fetch model catalog",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise_service_unavailable("Model catalog unavailable", cause=exc)

    normalized = [normalize_model_entry(m) for m in models]
    filtered: list[AIModel] = []
    for model in normalized:
        if not model.get("id"):
            continue
        if not model_matches_modality(model, modality):
            continue
        if free_only and not model.get("is_free"):
            continue
        filtered.append(AIModel(**model))

    filtered.sort(key=lambda m: (not m.is_free, m.name or m.id))

    logger.info(
        "AI model catalog response prepared",
        total_models=len(models),
        filtered_models=len(filtered),
        default_model=settings.primary_model,
        fallback_count=len(settings.fallback_models),
        modality_filter=modality,
        free_only=free_only,
    )

    return AIModelCatalogResponse(
        default_model=settings.primary_model,
        fallback_models=settings.fallback_models,
        models=filtered,
    )

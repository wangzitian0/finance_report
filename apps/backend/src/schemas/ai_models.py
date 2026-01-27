"""AI model catalog schemas."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ModelPricing(BaseModel):
    """Pricing information for an AI model."""

    model_config = ConfigDict(extra="allow")

    prompt: str | None = None
    completion: str | None = None
    image: str | None = None
    request: str | None = None


class AIModel(BaseModel):
    """Normalized AI model entry for UI selection."""

    id: str | None = None
    name: str | None = None
    is_free: bool = False
    input_modalities: list[str] = []
    pricing: ModelPricing | dict[str, str | Decimal | None] = {}


class AIModelCatalogResponse(BaseModel):
    """Response for the AI model catalog endpoint."""

    default_model: str
    fallback_models: list[str]
    models: list[AIModel]

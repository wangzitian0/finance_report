"""Pydantic schemas for the ``/llm`` config API (EPIC-023 AC23.4).

These shape the per-user LLM configuration surface: provider instances (API key
write-only — it is encrypted at rest and **never** returned), the dynamic model
catalogue, and the scene→model bindings. Enums are reused from ``src/llm/common``
so the API and the runtime contract can never drift.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.llm.common import Modality, ProtocolFamily, ReasoningEffort, Scene
from src.schemas.base import BaseResponse


class LlmConfigStatusResponse(BaseModel):
    """Whether the current user has a usable LLM configuration (drives first-run)."""

    configured: bool


class LlmProviderCreate(BaseModel):
    """Create a provider instance for the current user. ``api_key`` is write-only."""

    label: str = Field(min_length=1, max_length=100)
    protocol: ProtocolFamily
    api_key: str = Field(min_length=1, repr=False)
    api_base: str | None = Field(default=None, max_length=500)


class LlmProviderResponse(BaseResponse):
    """A configured provider. The API key is never returned — only its presence."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str
    protocol: ProtocolFamily
    api_base: str | None = None
    has_api_key: bool = True
    created_at: datetime
    updated_at: datetime


class LlmProviderListResponse(BaseModel):
    providers: list[LlmProviderResponse]


class LlmModelResponse(BaseModel):
    """One catalogue entry, enriched with litellm pricing / free-tier flag."""

    id: str
    provider_id: str
    modalities: list[Modality]
    is_free: bool
    input_price_per_mtok: Decimal | None = None
    output_price_per_mtok: Decimal | None = None
    supports_reasoning: bool = False


class LlmCatalogResponse(BaseModel):
    models: list[LlmModelResponse]


class LlmSceneBindingItem(BaseModel):
    """A scene→model binding (model + reasoning depth + fallbacks)."""

    scene: Scene
    provider_id: UUID
    model: str = Field(min_length=1, max_length=200)
    reasoning: ReasoningEffort = ReasoningEffort.NONE
    prefer_free: bool = False
    fallback_model_ids: list[str] = Field(default_factory=list)
    max_tokens: int | None = Field(default=None, gt=0)


class LlmScenesResponse(BaseModel):
    bindings: list[LlmSceneBindingItem]


class LlmScenesUpdate(BaseModel):
    """Replace the current user's scene bindings with this set (PUT semantics)."""

    bindings: list[LlmSceneBindingItem]

"""Pydantic schemas for the ``/llm`` config API (EPIC-023 AC23.4).

These shape the per-user LLM configuration surface: provider instances (API key
write-only — it is encrypted at rest and **never** returned), the dynamic model
catalogue, and the scene→model bindings. Enums are reused from ``src/llm/common``
so the API and the runtime contract can never drift.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.llm.common import Modality, ProtocolFamily, ReasoningEffort, Scene
from src.schemas.base import BaseResponse


class LlmConfigStatusResponse(BaseModel):
    """Whether the current user has a usable LLM configuration (drives first-run)."""

    configured: bool


class LlmProviderCreate(BaseModel):
    """Create a provider instance for the current user. ``api_key`` is write-only."""

    label: str = Field(min_length=1, max_length=100, description="Human-readable name for this provider instance.")
    protocol: ProtocolFamily = Field(description="The wire protocol family this provider speaks.")
    api_key: str = Field(
        min_length=1, repr=False, description="Provider API key; encrypted at rest and never returned."
    )
    api_base: str | None = Field(
        default=None, max_length=500, description="Custom API base URL for OpenAI-compatible endpoints."
    )

    @field_validator("api_base", mode="before")
    @classmethod
    def _validate_api_base(cls, value: object) -> str | None:
        """Blank → ``None``; otherwise require an absolute ``http(s)`` URL.

        ``api_base`` becomes an outbound endpoint, so reject non-URLs / non-http(s)
        schemes / whitespace here rather than letting a malformed value reach the
        HTTP client (a reliability + SSRF footgun)."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("api_base must be a string")
        trimmed = value.strip()
        if not trimmed:
            return None
        parsed = urlparse(trimmed)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("api_base must be an absolute http(s) URL")
        return trimmed


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


class LlmProviderDeleteResponse(BaseModel):
    """Confirmation that a provider (and its cascaded bindings) was deleted."""

    id: UUID = Field(description="The id of the deleted provider.")
    deleted: bool = Field(default=True, description="Always true when the provider was deleted.")


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

    scene: Scene = Field(description="The fixed call site this binding configures.")
    provider_id: UUID = Field(description="The provider instance (owned by the user) serving this scene.")
    model: str = Field(min_length=1, max_length=200, description="The model id to use for this scene.")
    reasoning: ReasoningEffort = Field(
        default=ReasoningEffort.NONE, description="Reasoning-effort depth for this scene."
    )
    prefer_free: bool = Field(default=False, description="Prefer a free-tier model when resolving this scene.")
    fallback_model_ids: list[str] = Field(
        default_factory=list, description="Ordered fallback model ids tried if the primary fails."
    )
    max_tokens: int | None = Field(default=None, gt=0, description="Optional max output tokens for this scene.")


class LlmScenesResponse(BaseModel):
    bindings: list[LlmSceneBindingItem]


class LlmScenesUpdate(BaseModel):
    """Replace the current user's scene bindings with this set (PUT semantics)."""

    bindings: list[LlmSceneBindingItem]

"""Pydantic schemas for the ``/llm`` config API (EPIC-023 AC23.4)."""

from __future__ import annotations

import ipaddress
import socket
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.llm import Modality, ProtocolFamily, ReasoningEffort, Scene
from src.schemas.base import BaseResponse

_BLOCKED_API_BASE_HOSTS = frozenset({"localhost", "metadata.google.internal", "metadata"})


def _api_base_host_is_blocked(host: str) -> bool:
    h = host.lower().strip("[]").rstrip(".")
    if h in _BLOCKED_API_BASE_HOSTS or h.endswith((".internal", ".local")):
        return True
    try:
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(h)
    except ValueError:
        try:
            ip = ipaddress.IPv4Address(socket.inet_aton(h))
        except (OSError, ValueError):
            return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


class LlmConfigStatusResponse(BaseModel):
    configured: bool


class LlmProviderCreate(BaseModel):
    label: Annotated[str, Field(min_length=1, max_length=100)]
    protocol: ProtocolFamily
    api_key: str = Field(min_length=1, repr=False, description="Encrypted provider API key.")
    api_base: Annotated[str, Field(max_length=500)] | None = None

    @field_validator("api_base", mode="before")
    @classmethod
    def _validate_api_base(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("api_base must be a string")
        if not (trimmed := value.strip()):
            return None
        parsed = urlparse(trimmed)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("api_base must be an absolute http(s) URL")
        if parsed.hostname is None or _api_base_host_is_blocked(parsed.hostname):
            raise ValueError("api_base host is not allowed (loopback/private/link-local/metadata)")
        return trimmed


class LlmProviderResponse(BaseResponse):
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
    id: UUID
    deleted: bool = True


class LlmModelResponse(BaseModel):
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
    scene: Scene
    provider_id: UUID
    model: Annotated[str, Field(min_length=1, max_length=200)]
    reasoning: ReasoningEffort = ReasoningEffort.NONE
    max_tokens: Annotated[int, Field(gt=0)] | None = None


class LlmScenesResponse(BaseModel):
    bindings: list[LlmSceneBindingItem]


class LlmScenesUpdate(BaseModel):
    bindings: list[LlmSceneBindingItem]

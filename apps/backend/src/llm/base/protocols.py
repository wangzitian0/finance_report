"""Service-facing protocols implemented by the litellm layer (EPIC A).

Scenes call these; they never see a provider id or model string directly — the
:class:`~src.llm.base.config_source.ConfigSource` resolves a
:class:`~src.llm.base.types.Scene` to a concrete model behind the protocol.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from src.llm.base.types import ChatResult, Message, Modality, ModelSpec, ReasoningEffort, Scene


@runtime_checkable
class LLMClient(Protocol):
    """Chat/extraction entry point, keyed by scene."""

    def stream(
        self,
        scene: Scene,
        messages: Sequence[Message],
        *,
        reasoning: ReasoningEffort | None = None,
    ) -> AsyncIterator[str]:
        """Stream plain-text delta chunks for ``scene``."""
        ...

    def stream_json(
        self,
        scene: Scene,
        messages: Sequence[Message],
        *,
        reasoning: ReasoningEffort | None = None,
    ) -> AsyncIterator[str]:
        """Stream raw delta chunks of a JSON response for ``scene``.

        JSON mode is prompt-driven (no ``response_format``) for the same reason as
        the legacy path: several providers reject it with multimodal inputs.
        """
        ...

    async def complete(
        self,
        scene: Scene,
        messages: Sequence[Message],
        *,
        reasoning: ReasoningEffort | None = None,
    ) -> ChatResult:
        """Non-streaming completion with token + cost telemetry."""
        ...


@runtime_checkable
class CatalogProvider(Protocol):
    """Dynamic model catalogue (axis 2)."""

    async def list_models(
        self,
        *,
        provider_id: str | None = None,
        modality: Modality | None = None,
        free_only: bool = False,
    ) -> list[ModelSpec]:
        """Available models, optionally filtered by provider/modality/free-tier."""
        ...

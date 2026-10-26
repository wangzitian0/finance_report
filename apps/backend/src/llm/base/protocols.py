"""Service-facing protocols implemented by the litellm layer (EPIC A).

Scenes call these; they never see a provider id or model string directly — the
:class:`~src.llm.base.config_source.ConfigSource` resolves a
:class:`~src.llm.base.types.Scene` to a concrete model behind the protocol.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from src.llm.base.types import Message, ReasoningEffort, Scene


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

"""Scene-keyed implementation of the published LLMClient port."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from uuid import UUID

from src.llm.base import (
    ConfigSource,
    DecodeParams,
    Message,
    ReasoningEffort,
    Scene,
)
from src.llm.extension.factory import get_config_source
from src.llm.extension.streaming import AIStreamError, _stream_ai_base


class LitellmClient:
    """Resolve a scene binding and execute it through the litellm transport."""

    def __init__(self, user_id: UUID | None, config_source: ConfigSource | None = None) -> None:
        self._user_id = user_id
        self._config_source = config_source or get_config_source(user_id)

    async def _resolve(self, scene: Scene) -> tuple[str, DecodeParams]:
        binding = await self._config_source.get_binding(scene)
        if binding is None:
            raise AIStreamError(f"No LLM binding configured for scene {scene.value}", retryable=False)
        return binding.model_id, DecodeParams(max_tokens=binding.max_tokens, reasoning=binding.reasoning)

    def _stream_bound(
        self,
        messages: Sequence[Message],
        *,
        model_id: str,
        decode: DecodeParams,
        mode_label: str,
    ) -> AsyncIterator[str]:
        async def generate() -> AsyncIterator[str]:
            async for chunk in _stream_ai_base(
                messages,
                model_id,
                user_id=self._user_id,
                timeout=120.0,
                decode=decode,
                mode_label=mode_label,
            ):
                yield chunk

        return generate()

    def _stream(
        self,
        scene: Scene,
        messages: Sequence[Message],
        *,
        reasoning: ReasoningEffort | None,
        mode_label: str,
    ) -> AsyncIterator[str]:
        async def generate() -> AsyncIterator[str]:
            model_id, configured = await self._resolve(scene)
            decode = DecodeParams(
                max_tokens=configured.max_tokens,
                reasoning=reasoning if reasoning is not None else configured.reasoning,
            )
            async for chunk in self._stream_bound(
                messages,
                model_id=model_id,
                decode=decode,
                mode_label=mode_label,
            ):
                yield chunk

        return generate()

    def stream(
        self,
        scene: Scene,
        messages: Sequence[Message],
        *,
        reasoning: ReasoningEffort | None = None,
    ) -> AsyncIterator[str]:
        """Stream plain-text chunks for a configured scene."""
        return self._stream(scene, messages, reasoning=reasoning, mode_label=scene.value)

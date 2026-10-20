"""Env-backed ``ConfigSource`` (EPIC-023 EPIC A).

A stopgap implementation that projects the existing provider-neutral env vars
(``AI_PROVIDER`` / ``AI_BASE_URL`` / ``AI_API_KEY`` / ``*_MODEL`` / ``*_FALLBACK_MODELS``)
onto the new scene×model contract, so the litellm client works with today's
configuration and behaviour is preserved. EPIC B replaces it with a
``DbConfigSource`` behind the same protocol.
"""

from __future__ import annotations

import src.config
from src.llm.base import ProtocolFamily, ProviderRef, ReasoningEffort, Scene, SceneBinding

# Bound from the bare published root (config publishes no named symbols).
settings = src.config.settings

_PROVIDER_ENV_ID = "env"

# Map the loosely-typed AI_PROVIDER value onto a protocol family. Anything that
# is not OpenRouter, Anthropic or Gemini is treated as OpenAI-compatible (Z.AI/GLM,
# DeepSeek, a local vLLM, …) — they all ride the OpenAI wire format.
_FAMILY_BY_PROVIDER: dict[str, ProtocolFamily] = {
    "openrouter": ProtocolFamily.OPENROUTER_COMPATIBLE,
    "anthropic": ProtocolFamily.ANTHROPIC_COMPATIBLE,
    "claude": ProtocolFamily.ANTHROPIC_COMPATIBLE,
    "gemini": ProtocolFamily.GOOGLE_GEMINI,
}


def protocol_for(provider: str) -> ProtocolFamily:
    return _FAMILY_BY_PROVIDER.get(provider.strip().lower(), ProtocolFamily.OPENAI_COMPATIBLE)


class EnvConfigSource:
    """Resolve providers/bindings from environment settings."""

    def _provider(self) -> ProviderRef | None:
        llm = settings.to_llm_settings()
        if not llm.api_key:
            return None
        return ProviderRef(
            id=_PROVIDER_ENV_ID,
            label=llm.provider,
            protocol=protocol_for(llm.provider),
            api_key=llm.api_key,
            api_base=llm.base_url or None,
        )

    async def list_providers(self) -> list[ProviderRef]:
        provider = self._provider()
        return [provider] if provider is not None else []

    async def get_provider(self, provider_id: str) -> ProviderRef | None:
        provider = self._provider()
        if provider is not None and provider.id == provider_id:
            return provider
        return None

    async def is_configured(self) -> bool:
        return self._provider() is not None

    async def get_binding(self, scene: Scene) -> SceneBinding | None:
        if self._provider() is None:
            return None
        return _binding_for(scene)


def _binding_for(scene: Scene) -> SceneBinding:
    """Map a scene to the model and reasoning of its infra2 SDK role (#2572).

    advisor.chat answers the user, so it uses the large role. Vision and OCR use the
    multimodal role. Every other scene uses the small role (PRIMARY_MODEL).
    """
    llm = settings.to_llm_settings()

    if scene is Scene.EXTRACTION_VISION:
        return SceneBinding(
            scene,
            llm.vision_model,
            fallback_model_ids=llm.vision_fallback_models,
            reasoning=ReasoningEffort(llm.role_reasoning_effort("multimodal")),
        )
    if scene is Scene.EXTRACTION_OCR:
        return SceneBinding(
            scene,
            llm.ocr_model,
            fallback_model_ids=llm.vision_fallback_models,
            reasoning=ReasoningEffort(llm.role_reasoning_effort("multimodal")),
        )
    if scene is Scene.ADVISOR_CHAT:
        return SceneBinding(
            scene,
            llm.large_model,
            fallback_model_ids=llm.fallback_models,
            reasoning=ReasoningEffort(llm.role_reasoning_effort("large")),
        )
    return SceneBinding(
        scene,
        llm.primary_model,
        fallback_model_ids=llm.fallback_models,
        reasoning=ReasoningEffort(llm.role_reasoning_effort("small")),
    )

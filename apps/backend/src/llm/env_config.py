"""Env-backed ``ConfigSource`` (EPIC-023 EPIC A).

A stopgap implementation that projects the existing provider-neutral env vars
(``AI_PROVIDER`` / ``AI_BASE_URL`` / ``AI_API_KEY`` / ``*_MODEL`` / ``*_FALLBACK_MODELS``)
onto the new scene×model contract, so the litellm client works with today's
configuration and behaviour is preserved. EPIC B replaces it with a
``DbConfigSource`` behind the same protocol.
"""

from __future__ import annotations

from src.config import settings
from src.llm.common import ProtocolFamily, ProviderRef, Scene, SceneBinding

_PROVIDER_ENV_ID = "env"

# Map the loosely-typed AI_PROVIDER value onto a protocol family. Anything that
# is not OpenRouter, Anthropic or Gemini is treated as OpenAI-compatible (Z.AI/GLM,
# DeepSeek, a local vLLM, …) — they all ride the OpenAI wire format.
_FAMILY_BY_PROVIDER: dict[str, ProtocolFamily] = {
    "openrouter": ProtocolFamily.OPENROUTER_COMPATIBLE,
    "anthropic": ProtocolFamily.ANTHROPIC_COMPATIBLE,
    "claude": ProtocolFamily.ANTHROPIC_COMPATIBLE,
    "gemini": ProtocolFamily.GOOGLE_GEMINI,
    "google": ProtocolFamily.GOOGLE_GEMINI,
}


def _protocol_for(provider: str) -> ProtocolFamily:
    return _FAMILY_BY_PROVIDER.get(provider.strip().lower(), ProtocolFamily.OPENAI_COMPATIBLE)


class EnvConfigSource:
    """Resolve providers/bindings from environment settings."""

    def _provider(self) -> ProviderRef | None:
        api_key = settings.ai_api_key
        if not api_key:
            return None
        return ProviderRef(
            id=_PROVIDER_ENV_ID,
            label=settings.ai_provider,
            protocol=_protocol_for(settings.ai_provider),
            api_key=api_key,
            api_base=settings.ai_base_url or None,
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
    """Map a scene to its env-configured model + fallbacks (behaviour-preserving)."""
    text_fallbacks = tuple(settings.fallback_models)
    vision_fallbacks = tuple(settings.vision_fallback_models)

    if scene is Scene.EXTRACTION_VISION:
        return SceneBinding(scene, settings.vision_model, fallback_model_ids=vision_fallbacks)
    if scene is Scene.EXTRACTION_OCR:
        return SceneBinding(scene, settings.ocr_model, fallback_model_ids=vision_fallbacks)
    # extraction.json / advisor.chat / statement.summary all use the primary model.
    return SceneBinding(scene, settings.primary_model, fallback_model_ids=text_fallbacks)

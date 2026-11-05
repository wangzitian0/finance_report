"""Env-backed ``ConfigSource`` (EPIC-023 EPIC A).

Projects the provider-neutral environment settings (``AI_PROVIDER`` /
``AI_BASE_URL`` / ``AI_API_KEY``) and the three canonical model roles
(``LARGE_MODEL``, ``SMALL_MODEL``, ``MULTIMODAL_MODEL``) onto the
scene×model contract.
"""

from __future__ import annotations

import re

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

    CANONICAL_ROLES: frozenset[str] = frozenset({"large", "small", "multimodal"})
    _RETIRED_GLM4_MODEL_RE = re.compile(r"^glm-?4(?:\.\d+)?v?$", re.IGNORECASE)

    @classmethod
    def default_role_for_scene(cls, scene: Scene) -> str:
        """Return the canonical SDK role ('large', 'small', or 'multimodal') for a scene."""
        if scene in (Scene.EXTRACTION_VISION, Scene.EXTRACTION_OCR):
            return "multimodal"
        if scene is Scene.ADVISOR_CHAT:
            return "large"
        return "small"

    @classmethod
    def is_retired_scene_model(cls, raw_model: str) -> bool:
        """Return True when ``raw_model`` names a retired fourth-generation model (#2624)."""
        cleaned = raw_model.strip()
        if not cleaned:
            return True
        bare = cleaned.split("/")[-1]
        return bool(cls._RETIRED_GLM4_MODEL_RE.match(bare))

    @classmethod
    def resolve_scene_model(cls, scene: Scene, raw_model: str | None) -> str:
        """Resolve a scene model binding through the three canonical roles (#2624)."""
        llm = settings.to_llm_settings()
        cleaned = (raw_model or "").strip()
        if not cleaned:
            return llm.role_model(cls.default_role_for_scene(scene))
        lowered = cleaned.lower()
        if lowered in cls.CANONICAL_ROLES:
            return llm.role_model(lowered)
        if cls.is_retired_scene_model(cleaned):
            return llm.role_model(cls.default_role_for_scene(scene))
        return cleaned

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
    multimodal role. Every other scene uses the small role. There is no fallback chain.
    """
    llm = settings.to_llm_settings()
    role = EnvConfigSource.default_role_for_scene(scene)
    return SceneBinding(
        scene,
        llm.role_model(role),
        reasoning=ReasoningEffort(llm.role_reasoning_effort(role)),
    )

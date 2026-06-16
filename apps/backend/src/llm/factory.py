"""Wiring for the LLM client + config source (EPIC-023 EPIC B).

The app resolves config DB-first with an env fallback: a deployment that has
configured providers in the DB uses them; one that only has the legacy
``AI_*`` env vars keeps working unchanged; one with neither is *unconfigured*
(``is_configured() == False``), which the first-run modal keys off. This is what
lets the DB-backed config land without breaking existing env-only deploys.
"""

from __future__ import annotations

from src.llm.client import LitellmClient
from src.llm.common import ConfigSource, ProviderRef, Scene, SceneBinding
from src.llm.cost import DailyBudgetMeter
from src.llm.db_config import DbConfigSource
from src.llm.env_config import EnvConfigSource


class LayeredConfigSource:
    """DB-primary config with an env fallback, behind the ``ConfigSource`` contract."""

    def __init__(self, primary: ConfigSource, fallback: ConfigSource) -> None:
        self._primary = primary
        self._fallback = fallback

    async def list_providers(self) -> list[ProviderRef]:
        primary = await self._primary.list_providers()
        return primary if primary else await self._fallback.list_providers()

    async def get_provider(self, provider_id: str) -> ProviderRef | None:
        found = await self._primary.get_provider(provider_id)
        return found if found is not None else await self._fallback.get_provider(provider_id)

    async def get_binding(self, scene: Scene) -> SceneBinding | None:
        binding = await self._primary.get_binding(scene)
        return binding if binding is not None else await self._fallback.get_binding(scene)

    async def is_configured(self) -> bool:
        return await self._primary.is_configured() or await self._fallback.is_configured()


def get_config_source() -> ConfigSource:
    """The deployment's config source: DB providers/bindings over env fallback."""
    return LayeredConfigSource(DbConfigSource(), EnvConfigSource())


def get_llm_client() -> LitellmClient:
    """The shared scene-keyed client, with the daily budget guard wired in."""
    return LitellmClient(get_config_source(), cost_meter=DailyBudgetMeter())

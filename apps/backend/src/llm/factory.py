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
    """DB-primary config with an env fallback, behind the ``ConfigSource`` contract.

    The fallback is **all-or-nothing**: if the primary (DB) has any provider, every
    lookup — providers *and* bindings — is served from the primary; otherwise every
    lookup comes from the fallback (env). This avoids mixing sources (e.g. an env
    binding's unqualified model resolved against DB providers), which would
    misroute or raise an ambiguity error.
    """

    def __init__(self, primary: ConfigSource, fallback: ConfigSource) -> None:
        self._primary = primary
        self._fallback = fallback

    async def _active(self) -> ConfigSource:
        return self._primary if await self._primary.is_configured() else self._fallback

    async def list_providers(self) -> list[ProviderRef]:
        return await (await self._active()).list_providers()

    async def get_provider(self, provider_id: str) -> ProviderRef | None:
        return await (await self._active()).get_provider(provider_id)

    async def get_binding(self, scene: Scene) -> SceneBinding | None:
        return await (await self._active()).get_binding(scene)

    async def is_configured(self) -> bool:
        return await self._primary.is_configured() or await self._fallback.is_configured()


def get_config_source() -> ConfigSource:
    """The deployment's config source: DB providers/bindings over env fallback."""
    return LayeredConfigSource(DbConfigSource(), EnvConfigSource())


def get_llm_client() -> LitellmClient:
    """The shared scene-keyed client, with the daily budget guard wired in."""
    return LitellmClient(get_config_source(), cost_meter=DailyBudgetMeter())

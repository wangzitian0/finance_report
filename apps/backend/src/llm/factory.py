"""Wiring for the LLM client + config source (EPIC-023 EPIC B).

The app resolves config DB-first with an env fallback: a deployment that has
configured providers in the DB uses them; one that only has the legacy
``AI_*`` env vars keeps working unchanged; one with neither is *unconfigured*
(``is_configured() == False``), which the first-run modal keys off. This is what
lets the DB-backed config land without breaking existing env-only deploys.
"""

from __future__ import annotations

from uuid import UUID

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


_budget_meter: DailyBudgetMeter | None = None


def get_budget_meter() -> DailyBudgetMeter:
    """The process-wide daily budget meter.

    The meter accumulates spend in memory, so it MUST be a singleton — a fresh
    ``DailyBudgetMeter()`` per request would reset ``spent_today`` to zero and the
    ``AI_DAILY_LIMIT_USD`` ceiling would never be enforced. (Per-process is still
    a floor: separate workers each keep their own tally — see ``DailyBudgetMeter``.)
    """
    global _budget_meter
    if _budget_meter is None:
        _budget_meter = DailyBudgetMeter()
    return _budget_meter


def get_config_source(user_id: UUID | None = None) -> ConfigSource:
    """The config source for a user: their DB providers/bindings, falling back to
    the deployment default, then the env config.

    ``user_id is None`` resolves the deployment default only (used by background /
    user-less paths). The DB layer is all-or-nothing per scope (see
    :class:`~src.llm.db_config.DbConfigSource`); the env fallback is all-or-nothing
    against the DB (see :class:`LayeredConfigSource`).
    """
    return LayeredConfigSource(DbConfigSource(user_id=user_id), EnvConfigSource())

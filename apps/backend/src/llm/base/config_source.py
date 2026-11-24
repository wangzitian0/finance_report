"""The configuration seam between the client and its settings.

The litellm client resolves a :class:`~src.llm.base.types.Scene` to a provider
and model purely through this protocol. The one implementation is
``EnvConfigSource``, which reads the environment (#2953 deleted the database one).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.llm.base.types import ProviderRef, Scene, SceneBinding


@runtime_checkable
class ConfigSource(Protocol):
    """Read-only resolver for provider instances and scene bindings."""

    async def list_providers(self) -> list[ProviderRef]:
        """All configured providers (API keys already decrypted)."""
        ...

    async def get_provider(self, provider_id: str) -> ProviderRef | None:
        """A single provider by id, or ``None`` if unknown."""
        ...

    async def get_binding(self, scene: Scene) -> SceneBinding | None:
        """The model binding for a scene, or ``None`` if unbound."""
        ...

    async def is_configured(self) -> bool:
        """Whether at least one provider exists.

        Drives the frontend first-run modal: ``False`` means "ask the user to add
        a provider before any AI feature can run".
        """
        ...

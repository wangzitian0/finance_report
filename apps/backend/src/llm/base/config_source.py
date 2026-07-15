"""The configuration seam between the client (EPIC A) and storage (EPIC B).

The litellm client resolves a :class:`~src.llm.base.types.Scene` to a provider
and model purely through this protocol. EPIC A ships an env-backed implementation
as a stopgap; EPIC B swaps in a ``DbConfigSource`` reading the
``llm_provider`` / ``llm_scene_binding`` tables — without the client changing.
Freezing this protocol is what lets the two halves proceed in parallel.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.llm.base.types.core import ProviderRef, Scene, SceneBinding


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

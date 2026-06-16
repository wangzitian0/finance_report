"""DB-backed ``ConfigSource`` (EPIC-023 EPIC B).

Reads provider instances + scene bindings from ``llm_providers`` /
``llm_scene_bindings``, decrypting each provider's API key on the way out. Bindings
are returned with their model qualified as ``{provider_id}/{model}`` so the client
resolves the exact provider even when several are configured.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.database import async_session_maker
from src.llm.common import Encrypted, ProviderRef, Scene, SceneBinding
from src.llm.common.secrets import SecretCipher, build_cipher
from src.models import LlmProvider, LlmSceneBinding


class DbConfigSource:
    """``ConfigSource`` over the ``llm_providers`` / ``llm_scene_bindings`` tables."""

    def __init__(
        self,
        session_maker: async_sessionmaker | None = None,
        cipher: SecretCipher | None = None,
    ) -> None:
        # Short-lived read sessions, decoupled from request scope.
        self._maker = session_maker or async_session_maker
        self._cipher_override = cipher

    def _cipher(self) -> SecretCipher:
        return self._cipher_override or build_cipher()

    def _to_ref(self, row: LlmProvider, cipher: SecretCipher) -> ProviderRef:
        api_key = cipher.decrypt(Encrypted(ciphertext=row.api_key_ciphertext, key_version=row.api_key_version))
        return ProviderRef(
            id=str(row.id),
            label=row.label,
            protocol=row.protocol,
            api_key=api_key,
            api_base=row.api_base,
        )

    async def list_providers(self) -> list[ProviderRef]:
        async with self._maker() as session:
            rows = (await session.execute(select(LlmProvider))).scalars().all()
        if not rows:
            return []
        cipher = self._cipher()
        return [self._to_ref(row, cipher) for row in rows]

    async def get_provider(self, provider_id: str) -> ProviderRef | None:
        try:
            pid = UUID(provider_id)
        except (ValueError, TypeError):
            return None
        async with self._maker() as session:
            row = await session.get(LlmProvider, pid)
        if row is None:
            return None
        return self._to_ref(row, self._cipher())

    async def get_binding(self, scene: Scene) -> SceneBinding | None:
        async with self._maker() as session:
            row = (
                await session.execute(select(LlmSceneBinding).where(LlmSceneBinding.scene == scene))
            ).scalar_one_or_none()
        if row is None:
            return None
        fallbacks = tuple(m.strip() for m in row.fallback_model_ids.split(",") if m.strip())
        return SceneBinding(
            scene=scene,
            # Qualify with the provider id so the client resolves the exact provider.
            model_id=f"{row.provider_id}/{row.model}",
            reasoning=row.reasoning,
            prefer_free=row.prefer_free,
            fallback_model_ids=fallbacks,
            max_tokens=row.max_tokens,
        )

    async def is_configured(self) -> bool:
        async with self._maker() as session:
            count = (await session.execute(select(func.count()).select_from(LlmProvider))).scalar_one()
        return count > 0

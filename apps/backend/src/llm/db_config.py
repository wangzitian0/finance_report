"""DB-backed ``ConfigSource`` (EPIC-023 EPIC B / per-user PR4).

Reads provider instances + scene bindings from ``llm_providers`` /
``llm_scene_bindings``, decrypting each provider's API key on the way out. Bindings
are returned with their model qualified as ``{provider_id}/{model}`` so the client
resolves the exact provider even when several are configured.

Since PR4 the source is **user-scoped with a deployment default** (AC23.4). A
``DbConfigSource`` is constructed for a specific user (or for the deployment
default when ``user_id is None``) and reads its scope *all-or-nothing*: if the
user owns any provider, both providers *and* bindings are served from the user's
rows; otherwise everything falls through to the deployment default (rows with
``user_id IS NULL``). This mirrors the env-fallback all-or-nothing rule and
avoids resolving a user binding's model against a deployment-default provider.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.database import async_session_maker, get_test_session_maker
from src.llm.common import Encrypted, ProviderRef, Scene, SceneBinding
from src.llm.common.secrets import SecretCipher, build_cipher
from src.models.llm_config import LlmProvider, LlmSceneBinding


class DbConfigSource:
    """``ConfigSource`` over the ``llm_providers`` / ``llm_scene_bindings`` tables."""

    def __init__(
        self,
        user_id: UUID | None = None,
        session_maker: async_sessionmaker | None = None,
        cipher: SecretCipher | None = None,
    ) -> None:
        # The scope this source reads: a user's own rows, else the deployment default.
        self._user_id = user_id
        # Short-lived read sessions, decoupled from request scope. Resolved lazily so
        # the test session maker (set via ``set_test_session_maker``) is honoured, like
        # ``get_db`` does; an explicit override always wins.
        self._maker_override = session_maker
        self._cipher_override = cipher

    @property
    def _maker(self) -> async_sessionmaker:
        return self._maker_override or get_test_session_maker() or async_session_maker

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

    async def _scope(self, session) -> UUID | None:
        """The effective scope to read from.

        The user's own id when they own at least one provider; otherwise ``None``
        (the deployment default). Resolving this once per read keeps providers and
        bindings on the same scope.
        """
        if self._user_id is None:
            return None
        count = (
            await session.execute(
                select(func.count()).select_from(LlmProvider).where(LlmProvider.user_id == self._user_id)
            )
        ).scalar_one()
        return self._user_id if count > 0 else None

    async def list_providers(self) -> list[ProviderRef]:
        async with self._maker() as session:
            scope = await self._scope(session)
            rows = (await session.execute(select(LlmProvider).where(LlmProvider.user_id == scope))).scalars().all()
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
            # Scope the lookup to the same scope bindings are read from (the user's
            # own rows, else the deployment default). Resolving by bare primary key
            # would return — and decrypt — another tenant's provider key.
            scope = await self._scope(session)
            row = (
                await session.execute(select(LlmProvider).where(LlmProvider.id == pid, LlmProvider.user_id == scope))
            ).scalar_one_or_none()
        if row is None:
            return None
        return self._to_ref(row, self._cipher())

    async def get_binding(self, scene: Scene) -> SceneBinding | None:
        async with self._maker() as session:
            scope = await self._scope(session)
            row = (
                await session.execute(
                    select(LlmSceneBinding).where(
                        LlmSceneBinding.scene == scene,
                        LlmSceneBinding.user_id == scope,
                    )
                )
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
        """True when this scope can serve: the user owns a provider, or a
        deployment default exists."""
        async with self._maker() as session:
            if self._user_id is not None:
                user_count = (
                    await session.execute(
                        select(func.count()).select_from(LlmProvider).where(LlmProvider.user_id == self._user_id)
                    )
                ).scalar_one()
                if user_count > 0:
                    return True
            default_count = (
                await session.execute(
                    select(func.count()).select_from(LlmProvider).where(LlmProvider.user_id.is_(None))
                )
            ).scalar_one()
        return default_count > 0

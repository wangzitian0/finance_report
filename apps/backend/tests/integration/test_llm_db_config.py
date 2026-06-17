"""DB-backed LLM config + env-fallback layering (EPIC-023 AC23.3.1, AC23.3.2).

DbConfigSource is pointed at the test's own session, so rows are written with
``flush`` (not ``commit``) and stay inside the test transaction — the db-fixture
rollback cleans up and nothing leaks across parallel xdist workers sharing a DB.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from cryptography.fernet import Fernet

from src.config import settings
from src.llm.common import FernetCipher, ProtocolFamily, ReasoningEffort, Scene
from src.llm.db_config import DbConfigSource
from src.llm.env_config import EnvConfigSource
from src.llm.factory import LayeredConfigSource
from src.models import LlmProvider, LlmSceneBinding


@pytest.fixture
def cipher() -> FernetCipher:
    return FernetCipher([Fernet.generate_key().decode("ascii")])


def _same_session_maker(session):
    """A session_maker that hands DbConfigSource the test's own (uncommitted)
    session, so flushed rows are visible without committing and rollback isolates."""

    @asynccontextmanager
    async def _cm():
        yield session

    return lambda: _cm()


async def test_AC23_3_1_db_config_reads_providers_and_bindings(db, cipher):
    """AC23.3.1: DbConfigSource decrypts the provider key and qualifies bindings by provider id."""
    sealed = cipher.encrypt("sk-db-secret")
    provider = LlmProvider(
        label="zai",
        protocol=ProtocolFamily.OPENAI_COMPATIBLE,
        api_key_ciphertext=sealed.ciphertext,
        api_key_version=sealed.key_version,
        api_base="https://api.z.ai",
    )
    db.add(provider)
    await db.flush()
    db.add(
        LlmSceneBinding(
            scene=Scene.EXTRACTION_JSON,
            provider_id=provider.id,
            model="glm-5.1",
            reasoning=ReasoningEffort.MEDIUM,
            prefer_free=False,
            fallback_model_ids="glm-5-turbo, glm-5",
            max_tokens=8192,
        )
    )
    await db.flush()

    source = DbConfigSource(session_maker=_same_session_maker(db), cipher=cipher)

    providers = await source.list_providers()
    mine = [p for p in providers if p.id == str(provider.id)]
    assert len(mine) == 1
    assert mine[0].api_key == "sk-db-secret"  # decrypted, never plaintext at rest
    assert mine[0].protocol is ProtocolFamily.OPENAI_COMPATIBLE
    assert mine[0].api_base == "https://api.z.ai"
    assert await source.is_configured() is True
    assert await source.get_provider(str(provider.id)) is not None

    binding = await source.get_binding(Scene.EXTRACTION_JSON)
    assert binding is not None
    assert binding.model_id == f"{provider.id}/glm-5.1"
    assert binding.reasoning is ReasoningEffort.MEDIUM
    assert binding.fallback_model_ids == ("glm-5-turbo", "glm-5")
    assert binding.max_tokens == 8192


async def test_AC23_4_8_get_provider_is_user_scoped_no_cross_tenant_key_disclosure(db, cipher):
    """AC23.4.8: get_provider must not resolve — or decrypt — another user's provider by id."""
    from uuid import uuid4

    from src.models import User

    user_a = User(email=f"a-{uuid4()}@example.com", hashed_password="x")
    user_b = User(email=f"b-{uuid4()}@example.com", hashed_password="x")
    db.add_all([user_a, user_b])
    await db.flush()

    sealed = cipher.encrypt("sk-user-a-secret")
    provider_a = LlmProvider(
        user_id=user_a.id,
        label="a-provider",
        protocol=ProtocolFamily.OPENAI_COMPATIBLE,
        api_key_ciphertext=sealed.ciphertext,
        api_key_version=sealed.key_version,
    )
    db.add(provider_a)
    await db.flush()

    # User B's source must not see user A's provider, by id or in the list.
    source_b = DbConfigSource(user_id=user_b.id, session_maker=_same_session_maker(db), cipher=cipher)
    assert await source_b.get_provider(str(provider_a.id)) is None
    assert all(p.id != str(provider_a.id) for p in await source_b.list_providers())

    # User A's own source resolves it (and decrypts) — the scope is per-owner, not global.
    source_a = DbConfigSource(user_id=user_a.id, session_maker=_same_session_maker(db), cipher=cipher)
    ref = await source_a.get_provider(str(provider_a.id))
    assert ref is not None and ref.api_key == "sk-user-a-secret"


async def test_AC23_3_2_layered_uses_db_first_then_env(db, cipher, monkeypatch):
    """AC23.3.2: with no DB binding for a scene, the layered source falls back to env config."""
    monkeypatch.setattr(settings, "ai_api_key", "env-key", raising=False)
    monkeypatch.setattr(settings, "ai_provider", "zai", raising=False)
    monkeypatch.setattr(settings, "ai_base_url", "https://api.z.ai", raising=False)
    monkeypatch.setattr(settings, "primary_model", "glm-5.1", raising=False)

    # DbConfigSource with no rows in this transaction -> layered resolves via env.
    layered = LayeredConfigSource(
        DbConfigSource(session_maker=_same_session_maker(db), cipher=cipher),
        EnvConfigSource(),
    )
    assert await layered.is_configured() is True
    binding = await layered.get_binding(Scene.ADVISOR_CHAT)
    assert binding is not None and binding.model_id == "glm-5.1"
    assert any(p.id == "env" for p in await layered.list_providers())


async def test_AC23_3_2_unconfigured_when_db_and_env_both_empty(db, cipher, monkeypatch):
    """AC23.3.2: no DB providers (this transaction) and no env key -> unconfigured."""
    monkeypatch.setattr(settings, "ai_api_key", "", raising=False)
    layered = LayeredConfigSource(
        DbConfigSource(session_maker=_same_session_maker(db), cipher=cipher),
        EnvConfigSource(),
    )
    # No DB provider in this transaction and no env key -> unconfigured.
    assert await layered.is_configured() is False
    assert await layered.list_providers() == []

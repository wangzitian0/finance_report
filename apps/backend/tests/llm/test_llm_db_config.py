from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

import src.llm.extension.factory as factory
from src.config import settings
from src.identity import User
from src.llm.base import FernetCipher, ProtocolFamily, ReasoningEffort, Scene
from src.llm.extension.db_config import DbConfigSource
from src.llm.extension.env_config import EnvConfigSource
from src.llm.extension.factory import LayeredConfigSource
from src.llm.orm.config import LlmProvider, LlmSceneBinding


@pytest.fixture
def cipher() -> FernetCipher:
    return FernetCipher([Fernet.generate_key().decode("ascii")])


def _same_session_maker(session):
    @asynccontextmanager
    async def _cm():
        yield session

    return lambda: _cm()


async def _add_user_provider(db, cipher: FernetCipher, *, email: str, label: str, secret: str, api_base: str | None = None) -> tuple[User, LlmProvider]:
    user = User(email=f"{email}-{uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    sealed = cipher.encrypt(secret)
    provider = LlmProvider(user_id=user.id, label=label, protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key_ciphertext=sealed.ciphertext, api_key_version=sealed.key_version, api_base=api_base)
    db.add(provider)
    await db.flush()
    return (user, provider)


async def test_AC23_3_and_4_db_config_providers_bindings_and_tenant_isolation(db, cipher) -> None:
    owner, provider = await _add_user_provider(db, cipher, email="owner", label="zai", secret="sk-db-secret", api_base="https://api.z.ai")
    db.add(LlmSceneBinding(user_id=owner.id, scene=Scene.EXTRACTION_JSON, provider_id=provider.id, model="glm-5.1", reasoning=ReasoningEffort.MEDIUM, max_tokens=8192))
    await db.flush()
    source = DbConfigSource(user_id=owner.id, session_maker=_same_session_maker(db), cipher=cipher)
    mine = [p for p in await source.list_providers() if p.id == str(provider.id)]
    binding = await source.get_binding(Scene.EXTRACTION_JSON)
    assert (len(mine), mine[0].api_key, mine[0].protocol, mine[0].api_base, await source.is_configured(), await source.get_provider(str(provider.id)) is not None) == (
        1, "sk-db-secret", ProtocolFamily.OPENAI_COMPATIBLE, "https://api.z.ai", True, True,
    )
    assert (binding.model_id, binding.reasoning, binding.max_tokens) == (f"{provider.id}/glm-5.1", ReasoningEffort.MEDIUM, 8192)

    user_a, provider_a = await _add_user_provider(db, cipher, email="a", label="a-provider", secret="sk-user-a-secret")
    user_b = User(email=f"b-{uuid4()}@example.com", hashed_password="x")
    db.add(user_b)
    await db.flush()
    src_a = DbConfigSource(user_id=user_a.id, session_maker=_same_session_maker(db), cipher=cipher)
    src_b = DbConfigSource(user_id=user_b.id, session_maker=_same_session_maker(db), cipher=cipher)
    ref_a = await src_a.get_provider(str(provider_a.id))
    assert await src_b.get_provider(str(provider_a.id)) is None and all(p.id != str(provider_a.id) for p in await src_b.list_providers()) and ref_a is not None and ref_a.api_key == "sk-user-a-secret"


async def test_AC23_3_2_layered_config_and_usage_singleton(db, cipher, monkeypatch) -> None:
    for attr, val in (("ai_api_key", "env-key"), ("ai_provider", "zai"), ("ai_base_url", "https://api.z.ai"), ("small_model", "glm-5.1"), ("large_model", "glm-5.1-large")):
        monkeypatch.setattr(settings, attr, val, raising=False)
    layered = LayeredConfigSource(DbConfigSource(session_maker=_same_session_maker(db), cipher=cipher), EnvConfigSource())
    binding = await layered.get_binding(Scene.ADVISOR_CHAT)
    assert (await layered.is_configured(), binding.model_id, any(p.id == "env" for p in await layered.list_providers())) == (True, "glm-5.1-large", True)
    monkeypatch.setattr(settings, "ai_api_key", "", raising=False)
    assert (await layered.is_configured(), await layered.list_providers()) == (False, [])
    factory._usage_meter = None
    assert factory.get_usage_meter() is factory.get_usage_meter()

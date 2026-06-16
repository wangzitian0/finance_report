"""DB-backed LLM config + env-fallback layering (EPIC-023 AC23.3.1, AC23.3.2)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from src.config import settings
from src.database import create_session_maker_from_db
from src.llm.common import FernetCipher, ProtocolFamily, ReasoningEffort, Scene
from src.llm.db_config import DbConfigSource
from src.llm.env_config import EnvConfigSource
from src.llm.factory import LayeredConfigSource
from src.models import LlmProvider, LlmSceneBinding


@pytest.fixture
def cipher() -> FernetCipher:
    return FernetCipher([Fernet.generate_key().decode("ascii")])


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
    await db.commit()

    source = DbConfigSource(session_maker=create_session_maker_from_db(db), cipher=cipher)

    providers = await source.list_providers()
    assert len(providers) == 1
    assert providers[0].api_key == "sk-db-secret"  # decrypted, never plaintext at rest
    assert providers[0].protocol is ProtocolFamily.OPENAI_COMPATIBLE
    assert providers[0].api_base == "https://api.z.ai"
    assert await source.is_configured() is True
    assert await source.get_provider(providers[0].id) is not None

    binding = await source.get_binding(Scene.EXTRACTION_JSON)
    assert binding is not None
    assert binding.model_id == f"{provider.id}/glm-5.1"
    assert binding.reasoning is ReasoningEffort.MEDIUM
    assert binding.fallback_model_ids == ("glm-5-turbo", "glm-5")
    assert binding.max_tokens == 8192
    assert await source.get_binding(Scene.ADVISOR_CHAT) is None


async def test_AC23_3_2_layered_uses_db_first_then_env(db, cipher, monkeypatch):
    """AC23.3.2: with the DB empty, the layered source falls back to env config."""
    monkeypatch.setattr(settings, "ai_api_key", "env-key", raising=False)
    monkeypatch.setattr(settings, "ai_provider", "zai", raising=False)
    monkeypatch.setattr(settings, "ai_base_url", "https://api.z.ai", raising=False)
    monkeypatch.setattr(settings, "primary_model", "glm-5.1", raising=False)

    layered = LayeredConfigSource(
        DbConfigSource(session_maker=create_session_maker_from_db(db), cipher=cipher),
        EnvConfigSource(),
    )
    assert await layered.is_configured() is True
    providers = await layered.list_providers()
    assert providers[0].id == "env"
    binding = await layered.get_binding(Scene.ADVISOR_CHAT)
    assert binding is not None and binding.model_id == "glm-5.1"


async def test_AC23_3_2_unconfigured_when_db_and_env_both_empty(db, cipher, monkeypatch):
    """AC23.3.2: no DB providers and no env key -> unconfigured (drives the first-run modal)."""
    monkeypatch.setattr(settings, "ai_api_key", "", raising=False)
    layered = LayeredConfigSource(
        DbConfigSource(session_maker=create_session_maker_from_db(db), cipher=cipher),
        EnvConfigSource(),
    )
    assert await layered.is_configured() is False
    assert await layered.list_providers() == []

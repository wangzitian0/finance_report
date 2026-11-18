from __future__ import annotations

import pytest
from infra2_sdk.runtime.llm import LlmSettings

import src.llm.extension.env_config as env_config
from src.config import Settings, settings
from src.llm.base import ProtocolFamily, ReasoningEffort, Scene
from src.llm.extension.env_config import EnvConfigSource


@pytest.fixture
def configured(monkeypatch) -> EnvConfigSource:
    for attr, val in (("ai_api_key", "test-key"), ("ai_provider", "zai"), ("ai_base_url", "https://api.z.ai"), ("small_model", "glm-5.1"), ("large_model", "large-test-model"), ("multimodal_model", "test-vision-model")):
        monkeypatch.setattr(settings, attr, val, raising=False)
    return EnvConfigSource()


async def test_AC23_2_4_unconfigured_and_configured_env_source(monkeypatch, configured: EnvConfigSource) -> None:
    providers = await configured.list_providers()
    advisor = await configured.get_binding(Scene.ADVISOR_CHAT)
    assert (len(providers), providers[0].protocol, providers[0].api_key, providers[0].api_base, await configured.is_configured(), await configured.get_provider("env") is not None, await configured.get_provider("nope")) == (
        1, ProtocolFamily.OPENAI_COMPATIBLE, "test-key", "https://api.z.ai", True, True, None,
    )
    assert ((await configured.get_binding(Scene.EXTRACTION_VISION)).model_id, (await configured.get_binding(Scene.EXTRACTION_OCR)).model_id, (await configured.get_binding(Scene.EXTRACTION_JSON)).model_id, advisor.model_id, advisor.reasoning, (await configured.get_binding(Scene.STATEMENT_SUMMARY)).model_id) == (
        "test-vision-model", "test-vision-model", "glm-5.1", "large-test-model", ReasoningEffort.HIGH, "glm-5.1",
    )

    monkeypatch.setattr(settings, "ai_api_key", "", raising=False)
    empty = EnvConfigSource()
    assert (await empty.is_configured(), await empty.list_providers(), await empty.get_binding(Scene.ADVISOR_CHAT)) == (False, [], None)


@pytest.mark.parametrize(("ai_provider", "expected"), [("openrouter", ProtocolFamily.OPENROUTER_COMPATIBLE), ("anthropic", ProtocolFamily.ANTHROPIC_COMPATIBLE), ("gemini", ProtocolFamily.GOOGLE_GEMINI)])
async def test_AC23_2_4_provider_protocol_families(monkeypatch, ai_provider: str, expected: ProtocolFamily) -> None:
    monkeypatch.setattr(settings, "ai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "ai_provider", ai_provider, raising=False)
    assert (await EnvConfigSource().list_providers())[0].protocol is expected


@pytest.mark.no_db
async def test_default_glm_models_cassette_settings_and_retired_resolution(monkeypatch) -> None:
    for variable in ("LARGE_MODEL", "SMALL_MODEL", "MULTIMODAL_MODEL"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(env_config, "settings", Settings(_env_file=None, LLM_PROVIDER="zai", LLM_API_KEY="test-key"))
    source, sdk = EnvConfigSource(), LlmSettings()
    for role, scene in (("small", Scene.EXTRACTION_JSON), ("small", Scene.STATEMENT_SUMMARY), ("large", Scene.ADVISOR_CHAT), ("multimodal", Scene.EXTRACTION_VISION), ("multimodal", Scene.EXTRACTION_OCR)):
        binding = await source.get_binding(scene)
        assert (binding.model_id, binding.reasoning) == (sdk.role_model(role), ReasoningEffort(sdk.role_reasoning_effort(role)))

    for env in ("LLM_CASSETTE_ENGAGE", "LLM_CASSETTE_REFRESH", "LLM_LIVE"):
        monkeypatch.setenv(env, "true")
    s = Settings(_env_file=None)
    assert s.llm_cassette_engage and s.llm_cassette_refresh and s.llm_live

    for attr, val in (("large_model", "large-role-model"), ("small_model", "small-role-model"), ("multimodal_model", "multimodal-role-model")):
        monkeypatch.setattr(env_config.settings, attr, val)
    assert (
        EnvConfigSource.default_role_for_scene(Scene.ADVISOR_CHAT), EnvConfigSource.default_role_for_scene(Scene.EXTRACTION_VISION), EnvConfigSource.default_role_for_scene(Scene.EXTRACTION_JSON),
        EnvConfigSource.is_retired_scene_model("   "), EnvConfigSource.is_retired_scene_model("glm-4.6"), EnvConfigSource.is_retired_scene_model("provider1/glm-4.6"), EnvConfigSource.is_retired_scene_model("glm-5.1"),
        EnvConfigSource.resolve_scene_model(Scene.ADVISOR_CHAT, None), EnvConfigSource.resolve_scene_model(Scene.ADVISOR_CHAT, "large"), EnvConfigSource.resolve_scene_model(Scene.ADVISOR_CHAT, "glm-4.6"),
        EnvConfigSource.resolve_scene_model(Scene.EXTRACTION_VISION, "multimodal"), EnvConfigSource.resolve_scene_model(Scene.EXTRACTION_JSON, "glm-5.1"),
    ) == ("large", "multimodal", "small", True, True, True, False, "large-role-model", "large-role-model", "large-role-model", "multimodal-role-model", "glm-5.1")

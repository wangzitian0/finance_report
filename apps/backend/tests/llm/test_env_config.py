"""Env-backed ConfigSource maps scenes behaviour-preservingly (EPIC-023 AC-llm.2.4)."""

from __future__ import annotations

import pytest
from infra2_sdk.runtime.llm import LlmSettings

from src.config import Settings, settings
from src.llm.base import ProtocolFamily, ReasoningEffort, Scene
from src.llm.extension.env_config import EnvConfigSource


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "ai_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "ai_provider", "zai", raising=False)
    monkeypatch.setattr(settings, "ai_base_url", "https://api.z.ai", raising=False)
    monkeypatch.setattr(settings, "primary_model", "glm-5.1", raising=False)
    monkeypatch.setattr(settings, "large_model", "large-test-model", raising=False)
    monkeypatch.setattr(settings, "vision_model", "test-vision-model", raising=False)
    monkeypatch.setattr(settings, "ocr_model", "test-vision-model", raising=False)
    return EnvConfigSource()


async def test_AC23_2_4_unconfigured_when_no_api_key(monkeypatch):
    """AC-llm.2.4: no API key -> not configured, no providers, no bindings (drives first-run modal)."""
    monkeypatch.setattr(settings, "ai_api_key", "", raising=False)
    src = EnvConfigSource()
    assert await src.is_configured() is False
    assert await src.list_providers() == []
    assert await src.get_binding(Scene.ADVISOR_CHAT) is None


async def test_AC23_2_4_provider_protocol_inferred_from_ai_provider(configured):
    """AC-llm.2.4: Z.AI maps to the openai-compatible family with its api_base + key."""
    providers = await configured.list_providers()
    assert len(providers) == 1
    p = providers[0]
    assert p.protocol is ProtocolFamily.OPENAI_COMPATIBLE
    assert p.api_key == "test-key"
    assert p.api_base == "https://api.z.ai"
    assert await configured.is_configured() is True


async def test_AC23_2_4_openrouter_and_anthropic_families(monkeypatch):
    """AC-llm.2.4: provider id selects the right protocol family."""
    monkeypatch.setattr(settings, "ai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "ai_provider", "openrouter", raising=False)
    assert (await EnvConfigSource().list_providers())[0].protocol is ProtocolFamily.OPENROUTER_COMPATIBLE
    monkeypatch.setattr(settings, "ai_provider", "anthropic", raising=False)
    assert (await EnvConfigSource().list_providers())[0].protocol is ProtocolFamily.ANTHROPIC_COMPATIBLE
    monkeypatch.setattr(settings, "ai_provider", "gemini", raising=False)
    assert (await EnvConfigSource().list_providers())[0].protocol is ProtocolFamily.GOOGLE_GEMINI


async def test_AC23_2_4_get_provider_by_id(configured):
    """AC-llm.2.4: get_provider returns the env provider by id, None otherwise."""
    assert (await configured.get_provider("env")) is not None
    assert (await configured.get_provider("nope")) is None


async def test_AC23_2_4_scene_bindings_match_configured_models(configured):
    """AC-llm.2.4: vision/ocr -> vision/ocr models; advisor.chat -> large model; the rest -> primary model."""
    assert (await configured.get_binding(Scene.EXTRACTION_VISION)).model_id == "test-vision-model"
    assert (await configured.get_binding(Scene.EXTRACTION_OCR)).model_id == "test-vision-model"
    assert (await configured.get_binding(Scene.EXTRACTION_JSON)).model_id == "glm-5.1"
    advisor = await configured.get_binding(Scene.ADVISOR_CHAT)
    assert advisor.model_id == "large-test-model"
    assert advisor.reasoning is ReasoningEffort.HIGH
    assert (await configured.get_binding(Scene.STATEMENT_SUMMARY)).model_id == "glm-5.1"


@pytest.mark.no_db
async def test_default_glm_models_reach_scene_bindings(monkeypatch):
    """AC-llm.2.8: the actual defaults route text and images to supported models."""
    import src.llm.extension.env_config as env_config

    for variable in (
        "PRIMARY_MODEL",
        "LARGE_MODEL",
        "VISION_MODEL",
        "OCR_MODEL",
        "FALLBACK_MODELS",
        "VISION_FALLBACK_MODELS",
    ):
        monkeypatch.delenv(variable, raising=False)
    defaults = Settings(_env_file=None, AI_PROVIDER="zai", AI_API_KEY="test-key")
    monkeypatch.setattr(env_config, "settings", defaults)
    source = EnvConfigSource()
    sdk = LlmSettings()
    for scene in (Scene.EXTRACTION_JSON, Scene.STATEMENT_SUMMARY):
        binding = await source.get_binding(scene)
        assert binding.model_id == sdk.primary_model
        assert binding.reasoning == ReasoningEffort(sdk.role_reasoning_effort("small"))
        assert binding.fallback_model_ids == sdk.fallback_models
    advisor = await source.get_binding(Scene.ADVISOR_CHAT)
    assert advisor.model_id == sdk.role_model("large")
    assert advisor.reasoning == ReasoningEffort(sdk.role_reasoning_effort("large"))
    assert advisor.fallback_model_ids == sdk.fallback_models
    vision = await source.get_binding(Scene.EXTRACTION_VISION)
    assert vision.model_id == (sdk.vision_model or sdk.primary_model)
    assert vision.fallback_model_ids == sdk.vision_fallback_models
    ocr = await source.get_binding(Scene.EXTRACTION_OCR)
    assert ocr.model_id == (sdk.ocr_model or sdk.primary_model)
    assert ocr.fallback_model_ids == sdk.vision_fallback_models


@pytest.mark.no_db
def test_llm_cassette_and_live_settings_fields(monkeypatch) -> None:
    """LLM cassette and live mode environment variables are declared on Settings."""
    monkeypatch.setenv("LLM_CASSETTE_ENGAGE", "true")
    monkeypatch.setenv("LLM_CASSETTE_REFRESH", "true")
    monkeypatch.setenv("LLM_LIVE", "true")

    s = Settings(_env_file=None)
    assert s.llm_cassette_engage is True
    assert s.llm_cassette_refresh is True
    assert s.llm_live is True

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.config import Settings
from src.runtime.extension.adapters import LlmCheck


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for name in ("LLM_API_KEY", "AI_API_KEY", "ZAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None)


def test_AC_runtime_env_ai_key_alias_1_resolution_and_probe(monkeypatch, tmp_path: Path) -> None:
    assert _settings(monkeypatch, LLM_API_KEY="canonical").ai_api_key == "canonical"
    assert _settings(monkeypatch, AI_API_KEY="legacy-ai", ZAI_API_KEY="legacy-zai").ai_api_key == ""
    assert _settings(monkeypatch, LLM_API_KEY="", ZAI_API_KEY="old").ai_api_key == ""
    assert _settings(monkeypatch).ai_api_key == ""

    for name in ("LLM_API_KEY", "AI_API_KEY", "ZAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for filename, content, expected in (("legacy.env", "ZAI_API_KEY=old\nAI_API_KEY=old-ai\n", ""), ("canonical.env", "ZAI_API_KEY=old\nLLM_API_KEY=canonical\n", "canonical")):
        p = tmp_path / filename
        p.write_text(content, encoding="utf-8")
        assert Settings(_env_file=str(p)).ai_api_key == expected

    for env, expected_status in (({"LLM_API_KEY": "canonical"}, "present"), ({"AI_API_KEY": "legacy-ai", "ZAI_API_KEY": "legacy-zai"}, "absent")):
        s = _settings(monkeypatch, **env)
        assert asyncio.run(LlmCheck(api_key=s.ai_api_key, provider=s.ai_provider, small_model=s.small_model, multimodal_model=s.multimodal_model).probe()).status.value == expected_status


_LLM_NAMES = ("LLM_PROVIDER", "AI_PROVIDER", "LLM_BASE_URL", "AI_BASE_URL")


def _llm_settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for name in _LLM_NAMES:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None)


def test_AC_runtime_env_llm_alias_retired_provider_and_base_url(monkeypatch) -> None:
    default = _llm_settings(monkeypatch)
    legacy = _llm_settings(monkeypatch, AI_PROVIDER="legacy-provider", AI_BASE_URL="https://legacy.example/v1")
    assert legacy.ai_provider == default.ai_provider
    assert legacy.ai_base_url == default.ai_base_url

    canonical = _llm_settings(monkeypatch, LLM_PROVIDER="canon-provider", LLM_BASE_URL="https://canon.example/v1")
    assert canonical.ai_provider == "canon-provider"
    assert canonical.ai_base_url == "https://canon.example/v1"

    both = _llm_settings(monkeypatch, LLM_PROVIDER="canon-provider", AI_PROVIDER="legacy-provider")
    assert both.ai_provider == "canon-provider"


def test_AC_runtime_env_llm_api_key_store_key_is_llm_api_key() -> None:
    from src.config import ENV_SOURCE_CLASSES

    assert Settings.model_fields["ai_api_key"].json_schema_extra["store_key"] == "LLM_API_KEY"
    assert ENV_SOURCE_CLASSES["ai_api_key"]["store_key"] == "LLM_API_KEY"

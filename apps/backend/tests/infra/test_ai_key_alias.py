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

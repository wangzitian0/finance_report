"AC-runtime.env-ai-key-alias.1"

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


def test_AC_runtime_env_ai_key_alias_1_only_canonical_llm_api_key_sets_the_key(monkeypatch) -> None:
    "AC-runtime.env-ai-key-alias.1"
    assert _settings(monkeypatch, LLM_API_KEY="canonical").ai_api_key == "canonical"
    assert _settings(monkeypatch, AI_API_KEY="legacy-ai", ZAI_API_KEY="legacy-zai").ai_api_key == ""


def test_AC_runtime_env_ai_key_alias_1_empty_canonical_leaves_key_empty(monkeypatch) -> None:
    assert _settings(monkeypatch, LLM_API_KEY="", ZAI_API_KEY="old").ai_api_key == ""
    assert _settings(monkeypatch).ai_api_key == ""


def test_AC_runtime_env_ai_key_alias_1_a_dotenv_file_only_reads_llm_api_key(monkeypatch, tmp_path: Path) -> None:
    for name in ("LLM_API_KEY", "AI_API_KEY", "ZAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    legacy_only = tmp_path / "legacy.env"
    legacy_only.write_text("ZAI_API_KEY=old\nAI_API_KEY=old-ai\n", encoding="utf-8")
    canonical = tmp_path / "canonical.env"
    canonical.write_text("ZAI_API_KEY=old\nLLM_API_KEY=canonical\n", encoding="utf-8")
    assert Settings(_env_file=str(legacy_only)).ai_api_key == ""
    assert Settings(_env_file=str(canonical)).ai_api_key == "canonical"


def test_AC_runtime_env_ai_key_alias_1_canonical_key_controls_llm_check(monkeypatch) -> None:
    present = _settings(monkeypatch, LLM_API_KEY="canonical")
    check_present = LlmCheck(
        api_key=present.ai_api_key,
        provider=present.ai_provider,
        small_model=present.small_model,
        multimodal_model=present.multimodal_model,
    )
    assert asyncio.run(check_present.probe()).status.value == "present"

    absent = _settings(monkeypatch, AI_API_KEY="legacy-ai", ZAI_API_KEY="legacy-zai")
    check_absent = LlmCheck(
        api_key=absent.ai_api_key,
        provider=absent.ai_provider,
        small_model=absent.small_model,
        multimodal_model=absent.multimodal_model,
    )
    assert asyncio.run(check_absent.probe()).status.value == "absent"

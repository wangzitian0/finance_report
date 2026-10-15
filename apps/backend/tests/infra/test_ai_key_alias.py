"""AC-runtime.env-ai-key-alias.1: Settings reads the AI key from AI_API_KEY or from ZAI_API_KEY (#2487).

Production still gets ZAI_API_KEY from infra2 (marker production/v1.2.35). The App reads
AI_API_KEY first. Without the old name, a production release of the App would start with an
empty key and report `llm: false`. Remove the old name after infra2 supplies AI_API_KEY in
production for the last three production releases.
"""

import asyncio
from pathlib import Path

import pytest
from common.testing.ac_proof import ac_proof

from src.config import Settings
from src.runtime.extension.adapters import LlmCheck


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None)


def test_AC_runtime_env_ai_key_alias_1_the_canonical_name_sets_the_key(monkeypatch) -> None:
    assert _settings(monkeypatch, AI_API_KEY="canonical").ai_api_key == "canonical"


@ac_proof(
    proof_id="test_AC_runtime_env_ai_key_alias_1_the_old_name_sets_the_key",
    ac_ids=["AC-runtime.env-ai-key-alias.1"],
    ci_tier="pr_ci",
)
def test_AC_runtime_env_ai_key_alias_1_the_old_name_sets_the_key(monkeypatch) -> None:
    """AC-runtime.env-ai-key-alias.1: ZAI_API_KEY alone sets the AI key."""
    assert _settings(monkeypatch, ZAI_API_KEY="old").ai_api_key == "old"


def test_AC_runtime_env_ai_key_alias_1_the_canonical_name_wins_when_both_are_set(
    monkeypatch,
) -> None:
    settings = _settings(monkeypatch, AI_API_KEY="canonical", ZAI_API_KEY="old")
    assert settings.ai_api_key == "canonical"


def test_AC_runtime_env_ai_key_alias_1_an_empty_canonical_name_falls_through(
    monkeypatch,
) -> None:
    settings = _settings(monkeypatch, AI_API_KEY="", ZAI_API_KEY="old")
    assert settings.ai_api_key == "old"


def test_AC_runtime_env_ai_key_alias_1_an_empty_old_name_leaves_the_key_empty(
    monkeypatch,
) -> None:
    assert _settings(monkeypatch, ZAI_API_KEY="").ai_api_key == ""


def test_AC_runtime_env_ai_key_alias_1_no_name_leaves_the_key_empty(monkeypatch) -> None:
    assert _settings(monkeypatch).ai_api_key == ""


def test_AC_runtime_env_ai_key_alias_1_a_dotenv_file_follows_the_same_order(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    only_old = tmp_path / "old.env"
    only_old.write_text("ZAI_API_KEY=old\n", encoding="utf-8")
    both = tmp_path / "both.env"
    both.write_text("ZAI_API_KEY=old\nAI_API_KEY=canonical\n", encoding="utf-8")

    assert Settings(_env_file=str(only_old)).ai_api_key == "old"
    assert Settings(_env_file=str(both)).ai_api_key == "canonical"


def test_AC_runtime_env_ai_key_alias_1_the_old_name_alone_makes_the_llm_check_present(
    monkeypatch,
) -> None:
    settings = _settings(monkeypatch, ZAI_API_KEY="old")
    check = LlmCheck(
        api_key=settings.ai_api_key,
        provider=settings.ai_provider,
        primary_model=settings.primary_model,
        ocr_model=settings.ocr_model,
    )

    result = asyncio.run(check.probe())

    assert result.status.value == "present"


def test_AC_runtime_env_ai_key_alias_1_no_name_makes_the_llm_check_absent(monkeypatch) -> None:
    settings = _settings(monkeypatch)
    check = LlmCheck(
        api_key=settings.ai_api_key,
        provider=settings.ai_provider,
        primary_model=settings.primary_model,
        ocr_model=settings.ocr_model,
    )

    result = asyncio.run(check.probe())

    assert result.status.value == "absent"

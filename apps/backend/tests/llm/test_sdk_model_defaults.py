"""The infra2 SDK owns the default models; the app adds none of its own (#2566, #2643)."""

from infra2_sdk.runtime.llm import LlmSettings

from src.config import Settings

ROLES = ("large", "small", "multimodal")
MODEL_ENV_VARS = ("LARGE_MODEL", "SMALL_MODEL", "MULTIMODAL_MODEL")


def _default_settings(monkeypatch) -> Settings:
    for name in MODEL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=None)


def test_AC_llm_sdk_model_defaults_1_app_defaults_equal_the_sdk_defaults(monkeypatch) -> None:
    """AC-llm.sdk-model-defaults.1: with no model variable set, every app model role equals the SDK default."""
    sdk = LlmSettings()
    settings = _default_settings(monkeypatch)
    assert settings.large_model == sdk.role_model("large")
    assert settings.small_model == sdk.role_model("small")
    assert settings.multimodal_model == sdk.role_model("multimodal")


def test_AC_llm_sdk_model_defaults_1_sdk_view_of_the_app_equals_the_sdk_defaults(monkeypatch) -> None:
    """AC-llm.sdk-model-defaults.1: the LlmSettings that the app hands to the SDK keep the SDK model defaults."""
    sdk = LlmSettings()
    handed = _default_settings(monkeypatch).to_llm_settings()
    for role in ROLES:
        assert handed.role_model(role) == sdk.role_model(role)
        assert handed.role_reasoning_effort(role) == sdk.role_reasoning_effort(role)


def test_AC_llm_sdk_model_defaults_1_production_may_override_one_role(monkeypatch) -> None:
    """AC-llm.sdk-model-defaults.1: an explicit model variable (a production customization) wins for its role only."""
    sdk = LlmSettings()
    _default_settings(monkeypatch)
    monkeypatch.setenv("SMALL_MODEL", "custom-production-model")
    settings = Settings(_env_file=None)
    assert settings.small_model == "custom-production-model"
    handed = settings.to_llm_settings()
    assert handed.role_model("small") == "custom-production-model"
    assert handed.role_model("large") == sdk.role_model("large")
    assert handed.role_model("multimodal") == sdk.role_model("multimodal")

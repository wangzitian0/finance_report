"""The infra2 SDK owns the default models; the app adds none of its own (#2566)."""

from infra2_sdk.runtime.llm import LlmSettings

from src.config import Settings

MODEL_ENV_VARS = (
    "PRIMARY_MODEL",
    "VISION_MODEL",
    "OCR_MODEL",
    "FALLBACK_MODELS",
    "VISION_FALLBACK_MODELS",
)


def _default_settings(monkeypatch) -> Settings:
    for name in MODEL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=None)


def test_AC_llm_sdk_model_defaults_1_app_defaults_equal_the_sdk_defaults(monkeypatch) -> None:
    """AC-llm.sdk-model-defaults.1: with no model variable set, every app model slot equals the SDK default."""
    sdk = LlmSettings()
    settings = _default_settings(monkeypatch)
    assert settings.primary_model == sdk.primary_model
    assert settings.vision_model == (sdk.vision_model or sdk.primary_model)
    assert settings.ocr_model == (sdk.ocr_model or sdk.primary_model)
    assert settings.fallback_models == list(sdk.fallback_models)
    assert settings.vision_fallback_models == list(sdk.vision_fallback_models)


def test_AC_llm_sdk_model_defaults_1_sdk_view_of_the_app_equals_the_sdk_defaults(monkeypatch) -> None:
    """AC-llm.sdk-model-defaults.1: the LlmSettings that the app hands to the SDK keep the SDK model defaults."""
    sdk = LlmSettings()
    handed = _default_settings(monkeypatch).to_llm_settings()
    assert handed.model_chain() == sdk.model_chain()
    assert handed.model_chain(vision=True) == sdk.model_chain(vision=True)
    assert handed.ocr_model == sdk.ocr_model


def test_AC_llm_sdk_model_defaults_1_production_may_override_a_model(monkeypatch) -> None:
    """AC-llm.sdk-model-defaults.1: an explicit model variable (a production customization) still wins."""
    _default_settings(monkeypatch)
    monkeypatch.setenv("PRIMARY_MODEL", "custom-production-model")
    settings = Settings(_env_file=None)
    assert settings.primary_model == "custom-production-model"
    assert settings.to_llm_settings().primary_model == "custom-production-model"


def test_AC_llm_sdk_model_defaults_1_fallbacks_follow_a_changed_sdk_default(monkeypatch) -> None:
    """AC-llm.sdk-model-defaults.1: the fallback lists follow the SDK, so non-empty SDK fallbacks reach the app."""
    import src.config as config_module

    _default_settings(monkeypatch)
    monkeypatch.setattr(
        config_module,
        "_SDK_LLM_DEFAULTS",
        LlmSettings(fallback_models=("sdk-text-fallback",), vision_fallback_models=("sdk-vision-fallback",)),
    )
    settings = Settings(_env_file=None)
    assert settings.fallback_models == ["sdk-text-fallback"]
    assert settings.vision_fallback_models == ["sdk-vision-fallback"]

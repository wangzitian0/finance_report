from infra2_sdk.runtime.llm import LlmSettings

from src.config import Settings

ROLES = ("large", "small", "multimodal")


def test_AC_llm_sdk_model_defaults_1(monkeypatch) -> None:
    for name in ("LARGE_MODEL", "SMALL_MODEL", "MULTIMODAL_MODEL"):
        monkeypatch.delenv(name, raising=False)
    sdk, defaults = LlmSettings(), Settings(_env_file=None)
    handed = defaults.to_llm_settings()
    assert all(getattr(defaults, f"{r}_model") == handed.role_model(r) == sdk.role_model(r) and handed.role_reasoning_effort(r) == sdk.role_reasoning_effort(r) for r in ROLES)

    monkeypatch.setenv("SMALL_MODEL", "custom-production-model")
    overridden = Settings(_env_file=None)
    handed_override = overridden.to_llm_settings()
    assert (overridden.small_model, handed_override.role_model("small"), handed_override.role_model("large"), handed_override.role_model("multimodal")) == (
        "custom-production-model", "custom-production-model", sdk.role_model("large"), sdk.role_model("multimodal"),
    )

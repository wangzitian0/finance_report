"""Every default model slot uses an approved model id (#2566)."""

from src.config import Settings
from src.llm.model_policy import APPROVED_MODEL_IDS

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


def test_AC_llm_approved_models_1_every_default_slot_is_approved(monkeypatch) -> None:
    """AC-llm.approved-models.1: primary, vision, OCR and every fallback default to an approved id."""
    assert APPROVED_MODEL_IDS == {"glm-5.3-flash", "glm-5.3-flashx"}

    settings = _default_settings(monkeypatch)
    slots = {
        "primary_model": [settings.primary_model],
        "vision_model": [settings.vision_model],
        "ocr_model": [settings.ocr_model],
        "fallback_models": settings.fallback_models,
        "vision_fallback_models": settings.vision_fallback_models,
    }
    for slot, model_ids in slots.items():
        assert model_ids, f"{slot} has no default model"
        outside = [model_id for model_id in model_ids if model_id not in APPROVED_MODEL_IDS]
        assert outside == [], f"{slot} defaults to models outside {sorted(APPROVED_MODEL_IDS)}: {outside}"


def test_AC_llm_approved_models_1_fallbacks_differ_from_their_primary(monkeypatch) -> None:
    """AC-llm.approved-models.1: each fallback list adds the other approved model, not a repeat of its primary."""
    settings = _default_settings(monkeypatch)
    assert settings.fallback_models == ["glm-5.3-flashx"]
    assert settings.vision_fallback_models == ["glm-5.3-flash"]

"""Every default model slot uses an approved model id (#2566)."""

from src.config import Settings
from src.llm.model_policy import APPROVED_MODEL_IDS, VISION_CAPABLE_MODEL_IDS

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
    assert VISION_CAPABLE_MODEL_IDS == {"glm-5.3-flashx"}
    assert VISION_CAPABLE_MODEL_IDS <= APPROVED_MODEL_IDS

    settings = _default_settings(monkeypatch)
    model_slots = {
        "primary_model": settings.primary_model,
        "vision_model": settings.vision_model,
        "ocr_model": settings.ocr_model,
    }
    for slot, model_id in model_slots.items():
        assert model_id in APPROVED_MODEL_IDS, f"{slot} defaults to {model_id!r}, outside the approved set"
    fallback_slots = {
        "fallback_models": settings.fallback_models,
        "vision_fallback_models": settings.vision_fallback_models,
    }
    for slot, model_ids in fallback_slots.items():
        outside = [model_id for model_id in model_ids if model_id not in APPROVED_MODEL_IDS]
        assert outside == [], f"{slot} defaults to models outside {sorted(APPROVED_MODEL_IDS)}: {outside}"


def test_AC_llm_approved_models_1_image_slots_use_a_vision_capable_model(monkeypatch) -> None:
    """AC-llm.approved-models.1: vision, OCR and vision fallbacks default to a vision-capable approved id."""
    settings = _default_settings(monkeypatch)
    image_models = [settings.vision_model, settings.ocr_model, *settings.vision_fallback_models]
    not_vision = [model_id for model_id in image_models if model_id not in VISION_CAPABLE_MODEL_IDS]
    assert not_vision == [], f"image slots default to models without image input: {not_vision}"


def test_AC_llm_approved_models_1_fallback_defaults(monkeypatch) -> None:
    """AC-llm.approved-models.1: the text fallback is the other approved model; the vision fallback is empty."""
    settings = _default_settings(monkeypatch)
    assert settings.primary_model == "glm-5.3-flash"
    assert settings.fallback_models == ["glm-5.3-flashx"]
    assert settings.vision_fallback_models == []

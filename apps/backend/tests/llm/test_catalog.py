"""Dynamic model catalogue with pricing + modality filters (EPIC-023 AC-llm.2.5)."""

from __future__ import annotations

from decimal import Decimal

import pytest

import src.llm.extension.catalog as catalog_mod
from src.config import settings
from src.llm.base import Modality
from src.llm.extension.catalog import LitellmCatalog


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(settings, "small_model", "glm-5.1")
    monkeypatch.setattr(settings, "large_model", "free-mini")
    monkeypatch.setattr(settings, "multimodal_model", "test-vision-model")
    # litellm pricing table: glm-5.1 priced, free-mini free.
    monkeypatch.setattr(
        catalog_mod.litellm,
        "model_cost",
        {
            "glm-5.1": {"input_cost_per_token": 0.0000006, "output_cost_per_token": 0.0000022},
            "free-mini": {"input_cost_per_token": 0.0, "output_cost_per_token": 0.0},
        },
        raising=False,
    )
    monkeypatch.setattr(catalog_mod.litellm, "supports_reasoning", lambda model: model == "glm-5.1", raising=False)
    return LitellmCatalog()


async def test_AC23_2_5_lists_configured_models_with_pricing(patched):
    """AC-llm.2.5: catalogue surfaces configured models with per-Mtok pricing as Decimal."""
    models = await patched.list_models()
    by_id = {m.id: m for m in models}
    assert "glm-5.1" in by_id
    primary = by_id["glm-5.1"]
    assert primary.input_price_per_mtok == Decimal("0.6")
    assert primary.output_price_per_mtok == Decimal("2.2")
    assert primary.is_free is False
    assert primary.supports_reasoning is True


async def test_AC23_2_5_flags_free_tier(patched):
    """AC-llm.2.5: a zero-priced model is flagged free; free_only filters to it."""
    free = await patched.list_models(free_only=True)
    assert {m.id for m in free} == {"free-mini"}
    assert all(m.is_free for m in free)


async def test_AC23_2_5_filters_by_modality(patched):
    """AC-llm.2.5: modality filter returns only models that accept it (vision models carry image)."""
    image_models = await patched.list_models(modality=Modality.IMAGE)
    assert "test-vision-model" in {m.id for m in image_models}
    assert "glm-5.1" not in {m.id for m in image_models}  # the small role is text-only


async def test_AC23_2_5_non_numeric_price_degrades_to_none(monkeypatch):
    """AC-llm.2.5: a malformed pricing entry yields None price, not a crash."""
    for role in ("small_model", "large_model", "multimodal_model"):
        monkeypatch.setattr(settings, role, "weird")
    monkeypatch.setattr(catalog_mod.litellm, "model_cost", {"weird": {"input_cost_per_token": "n/a"}}, raising=False)
    monkeypatch.setattr(catalog_mod.litellm, "supports_reasoning", lambda model: False, raising=False)
    models = await LitellmCatalog().list_models()
    assert models[0].input_price_per_mtok is None


async def test_AC23_2_5_dedupes_models(monkeypatch):
    """AC-llm.2.5: one model in two roles collapses to a single catalogue entry."""
    monkeypatch.setattr(settings, "small_model", "glm-5.1")
    monkeypatch.setattr(settings, "large_model", "glm-5.1")
    monkeypatch.setattr(settings, "multimodal_model", "test-vision-model")
    monkeypatch.setattr(catalog_mod.litellm, "model_cost", {}, raising=False)
    monkeypatch.setattr(catalog_mod.litellm, "supports_reasoning", lambda model: False, raising=False)

    ids = [m.id for m in await LitellmCatalog().list_models()]

    assert ids.count("glm-5.1") == 1
    assert ids == ["glm-5.1", "test-vision-model"]


async def test_AC23_2_5_one_model_in_every_role_merges_text_and_image_modalities(monkeypatch):
    """AC-llm.2.5: the SDK default is one model in all three roles: one entry that takes text and images."""
    for role in ("small_model", "large_model", "multimodal_model"):
        monkeypatch.setattr(settings, role, "glm-5.3-flash")
    monkeypatch.setattr(catalog_mod.litellm, "model_cost", {}, raising=False)
    monkeypatch.setattr(catalog_mod.litellm, "supports_reasoning", lambda model: False, raising=False)

    models = await LitellmCatalog().list_models()

    assert [m.id for m in models] == ["glm-5.3-flash"]
    assert Modality.TEXT in models[0].modalities
    assert Modality.IMAGE in models[0].modalities


async def test_AC23_2_5_three_different_models_are_ordered_by_modality(monkeypatch):
    """AC-llm.2.5: text lists put small, large, then multimodal; document modalities list only the multimodal model."""
    monkeypatch.setattr(settings, "small_model", "model-small")
    monkeypatch.setattr(settings, "large_model", "model-large")
    monkeypatch.setattr(settings, "multimodal_model", "model-multimodal")
    monkeypatch.setattr(catalog_mod.litellm, "model_cost", {}, raising=False)
    monkeypatch.setattr(catalog_mod.litellm, "supports_reasoning", lambda model: False, raising=False)

    catalog = LitellmCatalog()

    assert [m.id for m in await catalog.list_models()] == ["model-small", "model-large", "model-multimodal"]
    assert [m.id for m in await catalog.list_models(modality=Modality.TEXT)] == [
        "model-small",
        "model-large",
        "model-multimodal",
    ]
    for vision_modality in (Modality.IMAGE, Modality.PDF, Modality.FILE):
        assert [m.id for m in await catalog.list_models(modality=vision_modality)] == ["model-multimodal"]

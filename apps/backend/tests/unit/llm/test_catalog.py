"""Dynamic model catalogue with pricing + modality filters (EPIC-023 AC23.2.5)."""

from __future__ import annotations

from decimal import Decimal

import pytest

import src.llm.catalog as catalog_mod
from src.config import settings
from src.llm.catalog import LitellmCatalog
from src.llm.common import Modality


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(settings, "primary_model", "glm-5.1", raising=False)
    monkeypatch.setattr(settings, "vision_model", "glm-4.6v", raising=False)
    monkeypatch.setattr(settings, "ocr_model", "glm-4.6v", raising=False)
    monkeypatch.setattr(settings, "fallback_models_str", "free-mini", raising=False)
    monkeypatch.setattr(settings, "vision_fallback_models_str", None, raising=False)
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
    """AC23.2.5: catalogue surfaces configured models with per-Mtok pricing as Decimal."""
    models = await patched.list_models()
    by_id = {m.id: m for m in models}
    assert "glm-5.1" in by_id
    primary = by_id["glm-5.1"]
    assert primary.input_price_per_mtok == Decimal("0.6")
    assert primary.output_price_per_mtok == Decimal("2.2")
    assert primary.is_free is False
    assert primary.supports_reasoning is True


async def test_AC23_2_5_flags_free_tier(patched):
    """AC23.2.5: a zero-priced model is flagged free; free_only filters to it."""
    free = await patched.list_models(free_only=True)
    assert {m.id for m in free} == {"free-mini"}
    assert all(m.is_free for m in free)


async def test_AC23_2_5_filters_by_modality(patched):
    """AC23.2.5: modality filter returns only models that accept it (vision models carry image)."""
    image_models = await patched.list_models(modality=Modality.IMAGE)
    assert "glm-4.6v" in {m.id for m in image_models}
    assert "glm-5.1" not in {m.id for m in image_models}  # text-only primary


async def test_AC23_2_5_non_numeric_price_degrades_to_none(monkeypatch):
    """AC23.2.5: a malformed pricing entry yields None price, not a crash."""
    monkeypatch.setattr(settings, "primary_model", "weird", raising=False)
    monkeypatch.setattr(settings, "vision_model", "weird", raising=False)
    monkeypatch.setattr(settings, "ocr_model", "weird", raising=False)
    monkeypatch.setattr(settings, "fallback_models_str", None, raising=False)
    monkeypatch.setattr(settings, "vision_fallback_models_str", None, raising=False)
    monkeypatch.setattr(catalog_mod.litellm, "model_cost", {"weird": {"input_cost_per_token": "n/a"}}, raising=False)
    monkeypatch.setattr(catalog_mod.litellm, "supports_reasoning", lambda model: False, raising=False)
    models = await LitellmCatalog().list_models()
    assert models[0].input_price_per_mtok is None


async def test_AC23_2_5_dedupes_models(patched):
    """AC23.2.5: vision_model == ocr_model collapses to a single catalogue entry."""
    models = await patched.list_models()
    ids = [m.id for m in models]
    assert ids.count("glm-4.6v") == 1

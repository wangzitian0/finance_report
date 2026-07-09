"""Model catalogue integration via ``LitellmCatalog`` (EPIC-006 AC6.11.x).

EPIC-023 retired the remote-fetch ``services/ai_models`` catalogue in favour of the
local, deterministic :class:`~src.llm.extension.catalog.LitellmCatalog` (configured models +
litellm pricing). The AC6.11.x criteria — originally written against the remote
catalogue — are re-anchored here onto the catalogue's surviving behaviours.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.llm.base import Modality
from src.llm.extension.catalog import LitellmCatalog

pytestmark = pytest.mark.asyncio


async def test_AC6_11_1_catalog_lists_configured_models() -> None:
    """AC-llm.13.1: AC6.11.1: the catalogue lists the configured models, each with pricing fields."""
    specs = await LitellmCatalog().list_models()
    ids = {s.id for s in specs}
    assert settings.primary_model in ids
    assert settings.ocr_model in ids
    # Each entry carries the capability/pricing shape (data, not guesses).
    assert all(hasattr(s, "is_free") and hasattr(s, "modalities") for s in specs)


async def test_AC6_11_2_unknown_model_rejected() -> None:
    """AC-llm.13.2: AC6.11.2: model validation resolves a known model and rejects an unknown one."""
    catalog = LitellmCatalog()
    assert await catalog.get(settings.ocr_model) is not None
    assert await catalog.get("definitely-not-a-real-model-xyz") is None


async def test_AC6_11_3_catalog_is_local_deterministic() -> None:
    """AC-llm.13.3: AC6.11.3: the catalogue is local/deterministic — repeated calls agree (no remote fetch)."""
    catalog = LitellmCatalog()
    first = {s.id for s in await catalog.list_models()}
    second = {s.id for s in await catalog.list_models()}
    assert first == second
    assert first  # configured models are always present


async def test_AC6_11_4_catalog_modality_and_free_filters() -> None:
    """AC-llm.13.4: AC6.11.4: modality and free filters compose — every result satisfies both."""
    results = await LitellmCatalog().list_models(modality=Modality.IMAGE, free_only=True)
    assert all(s.accepts(Modality.IMAGE) and s.is_free for s in results)


async def test_AC6_11_5_model_modality_lookup() -> None:
    """AC-llm.13.5: AC6.11.5: per-model modality lookup — the vision/OCR model accepts image input."""
    spec = await LitellmCatalog().get(settings.vision_model)
    assert spec is not None
    assert spec.accepts(Modality.IMAGE)


async def test_AC6_11_6_catalog_get_bare_or_qualified() -> None:
    """AC-llm.13.6: AC6.11.6: ``get`` resolves a model id whether bare or provider-qualified."""
    catalog = LitellmCatalog()
    bare = await catalog.get(settings.ocr_model)
    qualified = await catalog.get(f"some-provider/{settings.ocr_model}")
    assert bare is not None
    assert qualified is not None
    assert bare.id == qualified.id

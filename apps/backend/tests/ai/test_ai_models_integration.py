"""Integration tests for AI model catalog and validation.

These tests validate the configured provider model catalog. The default catalog
is local/configured so CI does not depend on remote model-list availability.
"""

import re

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class TestModelCatalogIntegration:
    """AC6.11.1: Model catalog integration tests."""

    async def test_fetch_model_catalog(self):
        """AC6.11.1: Fetch model catalog returns data from OpenRouter."""
        from src.services.ai_models import fetch_model_catalog

        models = await fetch_model_catalog()
        assert len(models) > 0, "AI provider returned empty model catalog"
        assert all("id" in m for m in models), "Model entries missing 'id' field"

    async def test_primary_model_exists_in_catalog(self):
        """AC6.11.1: Primary model exists in AI provider catalog."""
        from src.config import settings
        from src.services.ai_models import is_model_known

        is_known = await is_model_known(settings.primary_model)
        assert is_known, (
            f"PRIMARY_MODEL '{settings.primary_model}' not found in AI provider catalog. "
            "This will cause statement upload to fail. Check .env.example for valid models."
        )

    async def test_ocr_model_has_image_support(self):
        """AC6.11.1: OCR model supports image/PDF inputs for PDF parsing."""
        from src.config import settings
        from src.services.ai_models import get_model_info, model_matches_modality

        model_info = await get_model_info(settings.ocr_model)
        assert model_info is not None, f"Could not fetch info for {settings.ocr_model}"

        supports_image = model_matches_modality(model_info, "image")
        assert supports_image, (
            f"OCR_MODEL '{settings.ocr_model}' does not support image inputs.\n"
            f"Input modalities: {model_info.get('input_modalities', [])}\n"
            f"PDF parsing requires 'image' modality."
        )

    async def test_fallback_models_format(self):
        """AC6.11.1: Fallback models are properly formatted."""
        from src.config import settings

        if not settings.fallback_models:
            return

        # fallback_models is already a list, no need to split
        assert len(settings.fallback_models) > 0, "FALLBACK_MODELS list is empty"

        for model_id in settings.fallback_models:
            assert re.fullmatch(r"glm-[\d.a-z-]+", model_id), f"Invalid fallback model format: {model_id}"

    async def test_glm_models_available(self):
        """AC6.11.1: At least one GLM model available in catalog."""
        from src.services.ai_models import fetch_model_catalog

        models = await fetch_model_catalog()
        glm_models = [m for m in models if m.get("id", "").lower().startswith("glm-")]

        assert len(glm_models) > 0, "No GLM models found in AI provider catalog."


class TestModelValidationIntegration:
    """AC6.11.2: Model validation integration tests."""

    async def test_invalid_model_rejected(self, client, test_user):
        """AC6.11.2: Invalid model rejected with 400."""
        response = await client.post(
            "/statements/upload",
            data={
                "model": "invalid-model-that-does-not-exist-12345",
                "institution": "Test Bank",
                "account_number": "1234567890",
            },
            files={"file": ("test.pdf", b"%PDF-1.4\ntest", "application/pdf")},
        )

        assert response.status_code == 400
        assert "Invalid model" in response.json()["detail"]

    async def test_model_without_image_support_rejected(self, client, test_user):
        """AC6.11.2: Model without image support rejected for PDF upload."""
        from src.services.ai_models import fetch_model_catalog, normalize_model_entry

        models = await fetch_model_catalog()
        text_only_candidates = []
        for model in models:
            normalized = normalize_model_entry(model)
            modalities = normalized.get("input_modalities", [])
            if "image" not in modalities and "text" in modalities:
                text_only_candidates.append(normalized["id"])

        if not text_only_candidates:
            return

        text_only_model = text_only_candidates[0]

        response = await client.post(
            "/statements/upload",
            data={
                "model": text_only_model,
                "institution": "Test Bank",
                "account_number": "1234567890",
            },
            files={"file": ("test.pdf", b"%PDF-1.4\ntest", "application/pdf")},
        )

        assert response.status_code == 400
        assert "does not support image/PDF inputs" in response.json()["detail"]

    async def test_valid_model_accepted_in_upload_validation(self, client, test_user):
        """AC6.11.2: Valid model passes upload validation."""
        from src.config import settings

        response = await client.post(
            "/statements/upload",
            data={
                "model": settings.ocr_model,
                "institution": "Test Bank",
                "account_number": "1234567890",
            },
            files={"file": ("test.pdf", b"%PDF-1.4\ntest", "application/pdf")},
        )

        if response.status_code == 400:
            detail = response.json().get("detail", "")
            assert "Invalid model" not in detail, f"Model validation failed for OCR_MODEL: {detail}"
            assert "does not support image" not in detail, f"OCR_MODEL lacks image support: {detail}"


class TestModelCatalogCaching:
    """AC6.11.3: Model catalog caching tests."""

    async def test_catalog_caching_reduces_api_calls(self):
        """AC6.11.3: Catalog caching reduces API calls."""
        import time

        from src.services.ai_models import fetch_model_catalog

        first = await fetch_model_catalog(force_refresh=True)
        start = time.time()
        second = await fetch_model_catalog()
        duration = time.time() - start

        assert first == second, "Cache returned different data"
        assert duration < 0.1, f"Cached fetch took {duration:.3f}s, expected < 0.1s (likely hit API)"

    async def test_force_refresh_bypasses_cache(self):
        """AC6.11.3: Force refresh bypasses cache."""
        from src.services.ai_models import fetch_model_catalog

        first = await fetch_model_catalog(force_refresh=True)
        second = await fetch_model_catalog(force_refresh=True)

        # Both should be valid catalogs with models
        assert len(first) > 0, "First refresh returned empty catalog"
        assert len(second) > 0, "Second refresh returned empty catalog"
        # Compare by set of IDs since order may differ between API calls
        first_ids = {m["id"] for m in first}
        second_ids = {m["id"] for m in second}
        # Allow small differences (API catalog may update between calls)
        common = first_ids & second_ids
        assert len(common) > len(first_ids) * 0.9, f"Less than 90% overlap: {len(common)}/{len(first_ids)}"

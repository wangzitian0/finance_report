"""Integration tests for AI model catalog and validation.

These tests hit real OpenRouter API to ensure configuration is valid.
Mark as @pytest.mark.integration to allow skipping for fast CI runs.
"""

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class TestModelCatalogIntegration:
    """Integration tests for OpenRouter model catalog."""

    async def test_fetch_model_catalog(self):
        """Test fetching models from OpenRouter returns data."""
        from src.services.openrouter_models import fetch_model_catalog

        models = await fetch_model_catalog()
        assert len(models) > 0, "OpenRouter returned empty model catalog"
        assert all("id" in m for m in models), "Model entries missing 'id' field"

    async def test_primary_model_exists_in_catalog(self):
        """Test that config.PRIMARY_MODEL exists in OpenRouter catalog."""
        from src.config import settings
        from src.services.openrouter_models import is_model_known

        is_known = await is_model_known(settings.primary_model)
        assert is_known, (
            f"PRIMARY_MODEL '{settings.primary_model}' not found in OpenRouter catalog. "
            "This will cause statement upload to fail. Check .env.example for valid models."
        )

    async def test_primary_model_has_image_support(self):
        """Test that PRIMARY_MODEL supports image inputs (required for PDF parsing)."""
        from src.config import settings
        from src.services.openrouter_models import get_model_info, model_matches_modality

        model_info = await get_model_info(settings.primary_model)
        assert model_info is not None, f"Could not fetch info for {settings.primary_model}"

        supports_image = model_matches_modality(model_info, "image")
        assert supports_image, (
            f"PRIMARY_MODEL '{settings.primary_model}' does not support image inputs.\n"
            f"Input modalities: {model_info.get('input_modalities', [])}\n"
            f"PDF parsing requires 'image' modality."
        )

    async def test_fallback_models_format(self):
        """Test that FALLBACK_MODELS are properly formatted."""
        from src.config import settings

        if not settings.fallback_models:
            return

        # fallback_models is already a list, no need to split
        assert len(settings.fallback_models) > 0, "FALLBACK_MODELS list is empty"

        for model_id in settings.fallback_models:
            assert "/" in model_id, f"Invalid fallback model format: {model_id}"
            assert len(model_id) > 5, f"Fallback model ID too short: {model_id}"

    async def test_gemini_models_available(self):
        """Test that at least one Gemini model is available in catalog."""
        from src.services.openrouter_models import fetch_model_catalog

        models = await fetch_model_catalog()
        gemini_models = [m for m in models if "gemini" in m.get("id", "").lower()]

        assert len(gemini_models) > 0, (
            "No Gemini models found in OpenRouter catalog. This suggests API connectivity issues."
        )


class TestModelCatalogCaching:
    """Test model catalog caching behavior."""

    async def test_catalog_caching_reduces_api_calls(self):
        """Test that fetching catalog multiple times uses cache."""
        import time

        from src.services.openrouter_models import fetch_model_catalog

        first = await fetch_model_catalog(force_refresh=True)
        start = time.time()
        second = await fetch_model_catalog()
        duration = time.time() - start

        assert first == second, "Cache returned different data"
        assert duration < 0.1, f"Cached fetch took {duration:.3f}s, expected < 0.1s (likely hit API)"

    async def test_force_refresh_bypasses_cache(self):
        """Test that force_refresh parameter bypasses cache."""
        from src.services.openrouter_models import fetch_model_catalog

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

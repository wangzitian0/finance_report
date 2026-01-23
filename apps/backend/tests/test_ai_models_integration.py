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
            pytest.skip("No fallback models configured")

        fallback_list = settings.fallback_models.split(",")
        assert len(fallback_list) > 0, "FALLBACK_MODELS list is empty"

        for model_id in fallback_list:
            model_id = model_id.strip()
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


class TestModelValidationIntegration:
    """Integration tests for model validation in upload flow."""

    async def test_invalid_model_rejected(self, client, test_user):
        """Test that uploading with invalid model returns 400."""
        response = await client.post(
            "/statements/upload",
            data={"model": "invalid-model-that-does-not-exist-12345"},
            files={"file": ("test.pdf", b"%PDF-1.4\ntest", "application/pdf")},
        )

        assert response.status_code == 400
        assert "Invalid model" in response.json()["detail"]

    async def test_model_without_image_support_rejected(self, client, test_user):
        """Test that models without image support are rejected for PDF upload."""
        from src.services.openrouter_models import fetch_model_catalog, normalize_model_entry

        models = await fetch_model_catalog()
        text_only_candidates = []
        for model in models:
            normalized = normalize_model_entry(model)
            modalities = normalized.get("input_modalities", [])
            if "image" not in modalities and "text" in modalities:
                text_only_candidates.append(normalized["id"])

        if not text_only_candidates:
            pytest.skip("No text-only models available for testing")

        text_only_model = text_only_candidates[0]

        response = await client.post(
            "/statements/upload",
            data={"model": text_only_model},
            files={"file": ("test.pdf", b"%PDF-1.4\ntest", "application/pdf")},
        )

        assert response.status_code == 400
        assert "does not support image inputs" in response.json()["detail"]

    async def test_valid_model_accepted_in_upload_validation(self, client, test_user):
        """Test that PRIMARY_MODEL passes validation in upload endpoint."""
        from src.config import settings

        response = await client.post(
            "/statements/upload",
            data={"model": settings.primary_model},
            files={"file": ("test.pdf", b"%PDF-1.4\ntest", "application/pdf")},
        )

        # Should fail on actual parsing (no MinIO), but model validation should pass
        # Status code should NOT be 400 with "Invalid model" message
        if response.status_code == 400:
            detail = response.json().get("detail", "")
            assert "Invalid model" not in detail, f"Model validation failed for PRIMARY_MODEL: {detail}"
            assert "does not support image" not in detail, f"PRIMARY_MODEL lacks image support: {detail}"


class TestModelCatalogCaching:
    """Test model catalog caching behavior."""

    async def test_catalog_caching_reduces_api_calls(self):
        """Test that fetching catalog multiple times uses cache."""
        from src.services.openrouter_models import fetch_model_catalog
        import time

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

        assert len(first) == len(second), "Refresh returned different catalog size"
        assert all(m1["id"] == m2["id"] for m1, m2 in zip(first, second)), "Refresh returned different model IDs"

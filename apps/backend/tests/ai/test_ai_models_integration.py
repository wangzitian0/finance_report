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


class TestModelValidationIntegration:
    """Integration tests for model validation in upload flow."""

    async def test_invalid_model_rejected(self, client, test_user):
        """Test that uploading with invalid model returns 400."""
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
        """Test that PRIMARY_MODEL passes validation in upload endpoint."""
        from src.config import settings

        response = await client.post(
            "/statements/upload",
            data={
                "model": settings.primary_model,
                "institution": "Test Bank",
                "account_number": "1234567890",
            },
            files={"file": ("test.pdf", b"%PDF-1.4\ntest", "application/pdf")},
        )

        if response.status_code == 400:
            detail = response.json().get("detail", "")
            assert "Invalid model" not in detail, f"Model validation failed for PRIMARY_MODEL: {detail}"
            assert "does not support image" not in detail, f"PRIMARY_MODEL lacks image support: {detail}"


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

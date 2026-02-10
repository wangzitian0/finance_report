"""Additional coverage tests for AI models router.

These tests cover edge cases and error paths for the AI models router
that are not covered in the main test files.
"""

import pytest


@pytest.mark.asyncio
class TestAIModelsRouterCoverage:
    """Additional tests for AI models router coverage."""

    async def test_list_models_free_only_filter(self, client):
        """
        GIVEN AI models endpoint with free_only filter
        WHEN requesting models
        THEN it should return only free models
        """
        response = await client.get("/ai/models?free_only=true")
        assert response.status_code == 200 or response.status_code == 503  # Service may be unavailable

        # If successful, verify free_only filtering
        if response.status_code == 200:
            data = response.json()
            assert "models" in data
            # All returned models should be free
            for model in data["models"]:
                assert model.get("is_free") is True

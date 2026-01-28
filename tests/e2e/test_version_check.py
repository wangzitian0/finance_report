"""
Version verification test.
Ensures the deployed application matches the source code version (Git SHA).
"""

import pytest
import httpx
import logging
from conftest import TestConfig

logger = logging.getLogger(__name__)


@pytest.mark.smoke
@pytest.mark.e2e
async def test_deployed_version_matches_source(config: TestConfig):
    """Verify that the deployed /health endpoint returns the expected Git SHA."""
    if not config.EXPECTED_SHA:
        logger.warning("Skipping version check: EXPECTED_SHA not set in environment")
        pytest.skip("EXPECTED_SHA not set")

    api_url = config.APP_URL.rstrip("/")
    health_url = f"{api_url}/api/health"

    logger.info(f"Checking version at {health_url} (Expected: {config.EXPECTED_SHA})")

    async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
        response = await client.get(health_url)
        assert response.status_code == 200, (
            f"Health check failed: {response.status_code}"
        )

        data = response.json()
        deployed_sha = data.get("git_sha")

        assert deployed_sha is not None, "Response missing 'git_sha' field"

        # Check for full match or short match
        # If expected is short (e.g. 7 chars), check if deployed starts with it
        # If deployed is short, check if expected starts with it
        if len(config.EXPECTED_SHA) != len(deployed_sha):
            # Short SHA comparison
            short_len = min(len(config.EXPECTED_SHA), len(deployed_sha))
            assert config.EXPECTED_SHA[:short_len] == deployed_sha[:short_len], (
                f"Version mismatch (short comparison)! Expected: {config.EXPECTED_SHA}, Got: {deployed_sha}"
            )
        else:
            assert deployed_sha == config.EXPECTED_SHA, (
                f"Version mismatch! Expected: {config.EXPECTED_SHA}, Got: {deployed_sha}"
            )

        logger.info("Version verification passed")

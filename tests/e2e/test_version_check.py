from __future__ import annotations

import logging
import os

import httpx
import pytest

from tests.e2e.deployment_pin import assert_pinned_deployment, resolve_expected_commit
from tests.e2e.conftest import TestConfig, _strict_e2e_gates_enabled

logger = logging.getLogger(__name__)


@pytest.mark.smoke
@pytest.mark.e2e
async def test_deployed_version_matches_source(config: TestConfig) -> None:
    if not config.EXPECTED_SHA:
        if (
            _strict_e2e_gates_enabled()
            or os.getenv("CI") == "true"
            or config.TEST_ENV != "local"
        ):
            pytest.fail(
                "Fatal: EXPECTED_SHA or APP_VERSION_REF must be explicitly set in CI, staging, and strict gate environments"
            )
        logger.warning("Skipping version check: EXPECTED_SHA and APP_VERSION_REF not set in environment")
        pytest.skip("EXPECTED_SHA not set")
    health_url = f"{config.APP_URL.rstrip('/')}/api/health"
    async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
        resp = await client.get(health_url)
        assert resp.status_code == 200, f"Health check failed: {resp.status_code}"
        payload = resp.json()
        assert payload.get("git_sha") is not None, "Response missing 'git_sha' field"
        # A release tag must match exactly; an observed SHA must name the tag's commit.
        assert_pinned_deployment(
            payload, config.EXPECTED_SHA, resolve_expected_commit(config.EXPECTED_SHA)
        )

from __future__ import annotations

import logging
import os

import httpx
import pytest

from tests.e2e.deployment_pin import resolve_expected_commit
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
        deployed_sha = resp.json().get("git_sha")
        assert deployed_sha is not None, "Response missing 'git_sha' field"
        expected = resolve_expected_commit(config.EXPECTED_SHA) or config.EXPECTED_SHA
        if len(expected) != len(deployed_sha):
            short_len = min(len(expected), len(deployed_sha))
            assert expected[:short_len] == deployed_sha[:short_len], (
                f"Version mismatch! Expected: {expected}, Got: {deployed_sha}"
            )
        else:
            assert deployed_sha == expected, (
                f"Version mismatch! Expected: {expected}, Got: {deployed_sha}"
            )

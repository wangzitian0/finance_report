from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from src.platform import RateLimitConfig, RateLimiter


def _unique_key() -> str:
    return f"test-{uuid.uuid4().hex}"


def test_rate_limiter_allows_blocks_isolates_and_resets() -> None:
    limiter = RateLimiter(RateLimitConfig(max_requests=2, window_seconds=60, block_seconds=100))
    k1, k2 = _unique_key(), _unique_key()
    assert [limiter.is_allowed(k1) for _ in range(2)] == [(True, 0), (True, 0)]
    allowed, retry = limiter.is_allowed(k1)
    assert not allowed and retry == 100
    assert limiter.is_allowed(k2)[0] is True
    limiter.reset(k1)
    assert limiter.is_allowed(k1)[0] is True
    limiter.reset(k1)
    limiter.reset(k2)
    limiter.reset(_unique_key())


@pytest.mark.parametrize(("method", "path", "allowed_rv", "expected_status"), [("get", "/health", (False, 30), None), ("get", "/docs", (False, 30), None), ("post", "/auth/login", (False, 30), 429), ("post", "/auth/login", (True, 0), None)])
async def test_global_rate_limit_middleware(public_client: AsyncClient, method: str, path: str, allowed_rv: tuple[bool, int], expected_status: int | None) -> None:
    from src.main import api_rate_limiter

    kwargs = {"json": {"email": "x@x.com", "password": "x"}} if method == "post" else {}
    with patch.object(api_rate_limiter, "is_allowed", return_value=allowed_rv) as mock_is_allowed:
        response = await getattr(public_client, method)(path, **kwargs)
    if expected_status == 429:
        assert response.status_code == 429 and "Retry-After" in response.headers and response.headers["X-Request-ID"]
        assert "Rate limit exceeded" in response.json()["detail"]
    else:
        assert response.status_code != 429
        if allowed_rv[0]:
            assert mock_is_allowed.called

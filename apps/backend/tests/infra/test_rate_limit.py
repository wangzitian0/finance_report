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


@pytest.mark.parametrize(
    ("method", "path", "allowed_rv", "expected_status"),
    [
        ("get", "/health", (False, 30), None),
        ("get", "/docs", (False, 30), None),
        ("post", "/auth/login", (False, 30), 429),
        ("post", "/auth/login", (True, 0), None),
    ],
)
async def test_global_rate_limit_middleware(
    public_client: AsyncClient, method: str, path: str, allowed_rv: tuple[bool, int], expected_status: int | None
) -> None:
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


def test_rate_limiter_evicts_expired_and_bounds_local_keys(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr("src.platform.extension.rate_limit.time.time", lambda: now[0])
    limiter = RateLimiter(RateLimitConfig(max_requests=2, window_seconds=10, block_seconds=30), max_keys=3)
    for key in ("ip-1", "ip-2", "ip-3", "ip-4"):
        assert limiter.is_allowed(key) == (True, 0)
    assert len(limiter._local_state) <= 3
    assert "ip-1" not in limiter._local_state

    now[0] += 50.0
    assert limiter.is_allowed("ip-5") == (True, 0)
    assert list(limiter._local_state.keys()) == ["ip-5"]


async def test_rate_limiter_async_uses_redis_resets_and_falls_back(monkeypatch) -> None:
    class _FakeRedis:
        def __init__(self) -> None:
            self.counts: dict[str, int] = {}
            self.deleted: list[str] = []

        async def eval(self, _script: str, _numkeys: int, window_key: str, block_key: str, *_args: object):
            count = self.counts.get(window_key, 0) + 1
            self.counts[window_key] = count
            if count > 2:
                return [0, 60]
            return [1, 0]

        async def delete(self, *keys: str) -> int:
            self.deleted.extend(keys)
            for key in keys:
                self.counts.pop(key, None)
            return len(keys)

        async def aclose(self) -> None:
            return None

    fake = _FakeRedis()
    limiter = RateLimiter(
        RateLimitConfig(max_requests=2, window_seconds=60, block_seconds=60),
        namespace="auth_login",
        redis_url="redis://127.0.0.1:6379/0",
    )
    monkeypatch.setattr(limiter, "_get_async_redis_client", lambda _url: fake)

    assert await limiter.is_allowed_async("10.0.0.1") == (True, 0)
    assert await limiter.is_allowed_async("10.0.0.1") == (True, 0)
    assert await limiter.is_allowed_async("10.0.0.1") == (False, 60)

    await limiter.reset_async("10.0.0.1")
    assert any("rl:auth_login:10.0.0.1" in k for k in fake.deleted)
    assert await limiter.is_allowed_async("10.0.0.1") == (True, 0)

    async def _broken_eval(*_args, **_kwargs):
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr(fake, "eval", _broken_eval)
    assert await limiter.is_allowed_async("10.0.0.2") == (True, 0)
    await limiter.clear_async()

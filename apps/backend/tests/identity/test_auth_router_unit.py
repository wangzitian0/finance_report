from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
import src.config
import src.identity.extension.api.auth as auth_module
from src.identity import LoginRequest, RegisterRequest, User, get_me, hash_password, login, register
from src.identity.extension.api.auth import _check_rate_limit, _get_client_ip
from src.platform import (
    RateLimitConfig,
    RateLimiter,
    ResourceNotFoundError,
    TooManyRequestsError,
    UnauthorizedError,
    ValidationFailedError,
)
from src.request_context import RequestContext


def _mock_request(client_ip: str = "127.0.0.1", x_forwarded_for: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", x_forwarded_for.encode())] if x_forwarded_for else []
    return Request({"type": "http", "method": "POST", "path": "/auth/test", "headers": headers, "client": (client_ip, 12345)})


async def test_register_creates_user_and_rejects_duplicate(db: AsyncSession) -> None:
    payload = RegisterRequest(email="direct@example.com", password="secret123", name="Direct")
    response = await register(_mock_request("192.168.1.100"), Response(), payload, db=db)
    assert (response.email, response.name) == ("direct@example.com", "Direct")
    with pytest.raises(ValidationFailedError, match="Email already registered"):
        await register(_mock_request("192.168.1.102"), Response(), payload, db=db)


async def test_login_and_get_me_direct(db: AsyncSession) -> None:
    user = User(email="login-direct@example.com", hashed_password=hash_password("correct123"))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    with pytest.raises(UnauthorizedError, match="Invalid email or password"):
        await login(_mock_request("192.168.1.101"), Response(), LoginRequest(email=user.email, password="wrong"), db=db)
    logged_in = await login(_mock_request("192.168.1.200"), Response(), LoginRequest(email=user.email, password="correct123"), db=db)
    assert logged_in.email == user.email

    me = await get_me(ctx=RequestContext(db=db, user_id=user.id), token="dummy-token")
    assert (me.id, me.email, me.access_token) == (user.id, user.email, "dummy-token")
    with pytest.raises(ResourceNotFoundError, match="User not found"):
        await get_me(ctx=RequestContext(db=db, user_id=uuid4()), token="dummy-token")


@pytest.mark.parametrize(("trust_proxy", "client_ip", "forwarded", "expected"), [(True, "10.0.0.1", "203.0.113.50, 198.51.100.1", "198.51.100.1"), (False, "192.168.1.99", "203.0.113.50", "192.168.1.99")])
def test_get_client_ip_proxy_modes(monkeypatch, trust_proxy: bool, client_ip: str, forwarded: str, expected: str) -> None:
    monkeypatch.setattr(src.config.settings, "trust_proxy", trust_proxy)
    assert _get_client_ip(_mock_request(client_ip=client_ip, x_forwarded_for=forwarded)) == expected


def test_check_rate_limit_enforces_429_and_logs_route_path(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(auth_module, "log_security_warning", lambda *args, **kwargs: calls.append(kwargs))
    limiter = RateLimiter(RateLimitConfig(max_requests=1, window_seconds=60, block_seconds=300))
    request = _mock_request("10.0.0.100")
    _check_rate_limit(request, limiter, "Rate limited")
    with pytest.raises(TooManyRequestsError) as exc_info:
        _check_rate_limit(request, limiter, "Rate limited")
    assert exc_info.value.status_code == 429 and "Rate limited" in str(exc_info.value.detail)
    assert "Retry-After" in exc_info.value.headers and calls[-1]["path"] == "/auth/test"

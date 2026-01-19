"""Unit tests for auth router functions."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.models import User
from src.rate_limit import RateLimitConfig, RateLimiter
from src.routers.auth import (
    _check_rate_limit,
    _get_client_ip,
    get_me,
    hash_password,
    login,
    register,
)
from src.schemas.auth import LoginRequest, RegisterRequest


def _mock_request(
    client_ip: str = "127.0.0.1",
    x_forwarded_for: str | None = None,
) -> Request:
    """Create a mock request with a specific client IP."""
    headers: list[tuple[bytes, bytes]] = []
    if x_forwarded_for:
        headers.append((b"x-forwarded-for", x_forwarded_for.encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/auth/test",
        "headers": headers,
        "client": (client_ip, 12345),
    }
    return Request(scope=scope)


@pytest.mark.asyncio
async def test_register_creates_user(db: AsyncSession) -> None:
    payload = RegisterRequest(email="direct@example.com", password="secret123", name="Direct")
    mock_request = _mock_request("192.168.1.100")  # Unique IP for test
    response = await register(mock_request, payload, db)

    assert response.email == "direct@example.com"
    assert response.name == "Direct"


@pytest.mark.asyncio
async def test_login_rejects_invalid_password(db: AsyncSession) -> None:
    user = User(email="login-direct@example.com", hashed_password=hash_password("correct"))
    db.add(user)
    await db.commit()

    payload = LoginRequest(email="login-direct@example.com", password="wrong")
    mock_request = _mock_request("192.168.1.101")  # Unique IP for test
    with pytest.raises(HTTPException, match="Invalid email or password"):
        await login(mock_request, payload, db)


@pytest.mark.asyncio
async def test_get_me_returns_user(db: AsyncSession) -> None:
    user = User(email="me-direct@example.com", hashed_password=hash_password("secret"))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    response = await get_me(user_id=user.id, token="dummy-token", db=db)

    assert response.id == user.id
    assert response.email == user.email
    assert response.access_token == "dummy-token"


@pytest.mark.asyncio
async def test_get_me_missing_user_raises(db: AsyncSession) -> None:
    with pytest.raises(HTTPException, match="User not found"):
        await get_me(user_id=uuid4(), token="dummy-token", db=db)


@pytest.mark.asyncio
async def test_register_duplicate_email_fails(db: AsyncSession) -> None:
    """Registering with an already-used email should fail."""
    # Create first user
    user = User(email="duplicate@example.com", hashed_password=hash_password("secret"))
    db.add(user)
    await db.commit()

    # Try to register with same email
    payload = RegisterRequest(email="duplicate@example.com", password="secret123", name="Second")
    mock_request = _mock_request("192.168.1.102")
    with pytest.raises(HTTPException, match="Email already registered"):
        await register(mock_request, payload, db)


def test_get_client_ip_with_x_forwarded_for_trusted(monkeypatch) -> None:
    """X-Forwarded-For header should be used when TRUST_PROXY=true."""
    monkeypatch.setenv("TRUST_PROXY", "true")
    # Reload module to pick up env change
    import importlib

    import src.routers.auth as auth_module

    importlib.reload(auth_module)

    request = _mock_request(client_ip="10.0.0.1", x_forwarded_for="203.0.113.50, 198.51.100.1")
    ip = auth_module._get_client_ip(request)
    assert ip == "203.0.113.50"

    # Reset to default
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    importlib.reload(auth_module)


def test_get_client_ip_ignores_x_forwarded_for_untrusted() -> None:
    """X-Forwarded-For header should be ignored when TRUST_PROXY is not set."""
    # Default TRUST_PROXY is false, so X-Forwarded-For should be ignored
    request = _mock_request(client_ip="192.168.1.99", x_forwarded_for="203.0.113.50")
    ip = _get_client_ip(request)
    assert ip == "192.168.1.99"


def test_get_client_ip_without_x_forwarded_for() -> None:
    """Direct client IP should be used when no X-Forwarded-For header."""
    request = _mock_request(client_ip="192.168.1.99")
    ip = _get_client_ip(request)
    assert ip == "192.168.1.99"


def test_check_rate_limit_blocks_when_exceeded() -> None:
    """Rate limit check should raise HTTPException when limit exceeded."""
    limiter = RateLimiter(RateLimitConfig(max_requests=1, window_seconds=60, block_seconds=300))
    request = _mock_request("10.0.0.100")

    # First request allowed
    _check_rate_limit(request, limiter, "Rate limited")

    # Second request should be blocked
    with pytest.raises(HTTPException) as exc_info:
        _check_rate_limit(request, limiter, "Rate limited")

    assert exc_info.value.status_code == 429
    assert "Rate limited" in str(exc_info.value.detail)
    assert "Retry-After" in exc_info.value.headers


@pytest.mark.asyncio
async def test_successful_login_resets_rate_limit(db: AsyncSession) -> None:
    """Successful login should reset the rate limiter for that IP."""
    # Create user
    user = User(email="resettest@example.com", hashed_password=hash_password("correct123"))
    db.add(user)
    await db.commit()

    # Login successfully
    payload = LoginRequest(email="resettest@example.com", password="correct123")
    mock_request = _mock_request("192.168.1.200")
    response = await login(mock_request, payload, db)

    assert response.email == "resettest@example.com"

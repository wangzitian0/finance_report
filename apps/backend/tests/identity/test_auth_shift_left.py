"""AC-identity.journeys.1-4: In-memory domain shift-left tests for authentication and session management.

Covers:
- AC-identity.journeys.1: User registration and token creation lifecycle.
- AC-identity.journeys.2: Authentication failure (invalid credentials / missing token) returns 401/422.
- AC-identity.journeys.3: Unauthenticated requests to protected endpoints are blocked with 401.
- AC-identity.journeys.4: User session JWT token is created, verified, and honors user ID.
- AC-testing.must-have.8, AC-testing.must-have.9
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.identity.base.types import normalize_email
from src.identity.extension.security import create_access_token, decode_access_token, hash_password, verify_password
from src.main import app


def test_password_hashing_and_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-identity.journeys.1, AC-testing.must-have.8:
    Password hashing produces salted hash and verifies accurately with optimal rounds.
    """
    import src.config

    password = "SecurePassword123!"
    hashed = hash_password(password)

    assert hashed != password
    assert hashed.startswith("$2b$04$")
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False

    # Protected environments (production, staging) preserve standard 12 rounds
    monkeypatch.setattr(src.config.settings, "environment", "production")
    prod_hashed = hash_password(password)
    assert prod_hashed.startswith("$2b$12$")
    assert verify_password(password, prod_hashed) is True

    monkeypatch.setattr(src.config.settings, "environment", "staging")
    staging_hashed = hash_password(password)
    assert staging_hashed.startswith("$2b$12$")
    assert verify_password(password, staging_hashed) is True


def test_jwt_session_token_lifecycle() -> None:
    """AC-identity.journeys.4:
    JWT session token encodes user ID, validates signature, and decodes payload.
    """
    user_id = str(uuid4())
    token = create_access_token(data={"sub": user_id})

    assert isinstance(token, str)
    assert len(token) > 20

    decoded = decode_access_token(token)
    assert decoded is not None
    assert decoded.get("sub") == user_id


async def test_unauthenticated_request_blocked() -> None:
    """AC-identity.journeys.3:
    Unauthenticated requests to protected endpoints are blocked with 401.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/accounts")

    assert response.status_code == 401
    assert "Not authenticated" in response.text or "credentials" in response.text


async def test_invalid_token_rejected_with_401() -> None:
    """AC-identity.journeys.2, AC-testing.must-have.9:
    Invalid bearer token is rejected with 401 without 500 error.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer invalid-garbage-token"},
    ) as ac:
        response = await ac.get("/accounts")

    assert response.status_code == 401


def test_email_normalization_and_validation() -> None:
    """AC-identity.journeys.1:
    Email normalization strips whitespace and converts to lowercase.
    """
    raw_email = "  TestUser@Example.COM  "
    normalized = normalize_email(raw_email)
    assert normalized == "testuser@example.com"

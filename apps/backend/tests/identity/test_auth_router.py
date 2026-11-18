from __future__ import annotations

import pytest
from fastapi import Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from src.identity import User, create_access_token, hash_password
from src.identity.extension.api import auth as auth_router
from src.platform import ValidationFailedError, get_client_ip
from tests.factories import UserFactory


async def test_register_success(public_client):
    resp = await public_client.post(
        "/auth/register", json={"email": "newuser@example.com", "password": "password123", "name": "New User"}
    )
    data = resp.json()
    assert resp.status_code == 201 and (data["email"], data["name"], data["token_type"]) == (
        "newuser@example.com",
        "New User",
        "bearer",
    )
    assert "id" in data and "access_token" in data and resp.cookies.get("finance_access_token")


@pytest.mark.parametrize("attempt_email", ["existing@example.com", "Existing@Example.COM"])
async def test_register_duplicate_email_rejected(db: AsyncSession, public_client, attempt_email: str):
    await UserFactory.create_async(db, email="existing@example.com", hashed_password=hash_password("password123"))
    await db.commit()
    resp = await public_client.post("/auth/register", json={"email": attempt_email, "password": "password123"})
    assert resp.status_code == 400 and resp.json()["detail"] == "Email already registered"


@pytest.mark.parametrize("login_email", ["loginuser@example.com", "LOGINUSER@EXAMPLE.COM"])
async def test_login_success_exact_and_normalized_email(db: AsyncSession, public_client, login_email: str):
    user = await UserFactory.create_async(
        db, email="loginuser@example.com", hashed_password=hash_password("secretpassword")
    )
    await db.commit()
    resp = await public_client.post("/auth/login", json={"email": login_email, "password": "secretpassword"})
    data = resp.json()
    assert resp.status_code == 200 and (data["email"], data["id"], data["token_type"]) == (
        "loginuser@example.com",
        str(user.id),
        "bearer",
    )
    assert "access_token" in data and resp.cookies.get("finance_access_token")


@pytest.mark.parametrize(
    ("email", "password", "seed_user"),
    [("wrongpass@example.com", "wrongpassword", True), ("ghost@example.com", "password123", False)],
)
async def test_login_rejects_invalid_credentials(
    db: AsyncSession, public_client, email: str, password: str, seed_user: bool
):
    if seed_user:
        await UserFactory.create_async(db, email="wrongpass@example.com", hashed_password=hash_password("correctpass"))
        await db.commit()
    resp = await public_client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 401 and (not seed_user or resp.json()["detail"] == "Invalid email or password")


async def test_get_me_bearer_cookie_and_missing_user(client, public_client, test_user):
    resp = await client.get("/auth/me")
    assert resp.status_code == 200 and (resp.json()["id"], resp.json()["email"]) == (str(test_user.id), test_user.email)
    public_client.cookies.set("finance_access_token", create_access_token(data={"sub": str(test_user.id)}))
    cookie_resp = await public_client.get("/auth/me")
    assert cookie_resp.status_code == 200 and cookie_resp.json()["id"] == str(test_user.id)
    missing_resp = await public_client.get(
        "/auth/me",
        headers={
            "Authorization": f"Bearer {create_access_token(data={'sub': '00000000-0000-0000-0000-000000000000'})}"
        },
    )
    assert missing_resp.status_code == 401 and missing_resp.json()["detail"] == "User not found"


async def test_register_integrity_error_race_condition(monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    @asynccontextmanager
    async def _nested():
        yield

    fake_db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)),
        add=lambda _obj: None,
        begin_nested=_nested,
        flush=AsyncMock(side_effect=IntegrityError("x", {}, Exception("dup"))),
        refresh=AsyncMock(),
    )
    monkeypatch.setattr(auth_router, "_check_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth_router.register_rate_limiter, "reset", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth_router, "hash_password", lambda _password: "hashed")
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    payload = auth_router.RegisterRequest(email="race@example.com", password="password123", name="Race User")
    with pytest.raises(ValidationFailedError) as exc_info:
        await auth_router.register(request=request, response=Response(), data=payload, db=fake_db)
    assert (exc_info.value.status_code, exc_info.value.detail) == (400, "Email already registered")


async def test_browser_logout_expires_cookie(public_client):
    public_client.base_url = public_client.base_url.copy_with(scheme="https")
    payload = {"email": "logout@example.com", "password": "SyntheticLogout123!"}
    registered = await public_client.post("/auth/register", json=payload)
    assert registered.status_code == 201 and (await public_client.get("/auth/me")).status_code == 200
    token = registered.json()["access_token"]

    logged_out = await public_client.post("/auth/logout")
    cookie = logged_out.headers["set-cookie"].lower()
    assert (logged_out.status_code, logged_out.content) == (204, b"")
    assert all(part in cookie for part in ("max-age=0", "path=/", "httponly", "samesite=lax"))
    assert public_client.cookies.get("finance_access_token") is None
    assert (await public_client.get("/auth/me")).status_code == 401
    assert (await public_client.post("/auth/logout")).status_code == 204
    assert (await public_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 200
    assert (await public_client.post("/auth/login", json=payload)).status_code == 200
    assert (await public_client.get("/auth/me")).status_code == 200


async def test_soft_deleted_user_email_can_reregister(db: AsyncSession, public_client) -> None:
    db.add(User(email="reclaim@example.com", hashed_password=hash_password("oldpassword123"), is_deleted=True))
    await db.commit()
    resp = await public_client.post(
        "/auth/register", json={"email": "Reclaim@Example.com", "password": "newpassword123", "name": "Reclaimed"}
    )
    assert resp.status_code == 201 and resp.json()["email"] == "reclaim@example.com"
    dup_resp = await public_client.post(
        "/auth/register", json={"email": "reclaim@example.com", "password": "anotherpassword123"}
    )
    assert dup_resp.status_code == 400 and dup_resp.json()["detail"] == "Email already registered"


def test_get_client_ip_uses_rightmost_forwarded_ip_and_shares_helper(monkeypatch) -> None:
    import src.config
    import src.main as main_module

    assert not hasattr(auth_router, "TRUST_PROXY")
    assert auth_router._get_client_ip is get_client_ip and main_module.get_client_ip is get_client_ip
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/login",
            "headers": [(b"x-forwarded-for", b"1.2.3.4, 198.51.100.77")],
            "client": ("10.0.0.1", 12345),
        }
    )
    for trust_proxy, expected_ip in ((False, "10.0.0.1"), (True, "198.51.100.77")):
        monkeypatch.setattr(src.config.settings, "trust_proxy", trust_proxy)
        assert get_client_ip(request, trust_proxy=trust_proxy) == expected_ip
        assert auth_router._get_client_ip(request) == expected_ip

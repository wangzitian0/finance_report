"""Unit tests for auth router functions."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User
from src.routers.auth import get_me, hash_password, login, register
from src.schemas.auth import LoginRequest, RegisterRequest


@pytest.mark.asyncio
async def test_register_creates_user(db: AsyncSession) -> None:
    payload = RegisterRequest(email="direct@example.com", password="secret123", name="Direct")
    response = await register(payload, db)

    assert response.email == "direct@example.com"
    assert response.name == "Direct"


@pytest.mark.asyncio
async def test_login_rejects_invalid_password(db: AsyncSession) -> None:
    user = User(email="login-direct@example.com", hashed_password=hash_password("correct"))
    db.add(user)
    await db.commit()

    payload = LoginRequest(email="login-direct@example.com", password="wrong")
    with pytest.raises(HTTPException, match="Invalid email or password"):
        await login(payload, db)


@pytest.mark.asyncio
async def test_get_me_returns_user(db: AsyncSession) -> None:
    user = User(email="me-direct@example.com", hashed_password=hash_password("secret"))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    response = await get_me(user_id=user.id, db=db)

    assert response.id == user.id
    assert response.email == user.email


@pytest.mark.asyncio
async def test_get_me_missing_user_raises(db: AsyncSession) -> None:
    with pytest.raises(HTTPException, match="User not found"):
        await get_me(user_id=uuid4(), db=db)

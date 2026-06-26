"""API tests for EPIC-018 AI user settings endpoints."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.user import User

pytestmark = pytest.mark.asyncio


async def test_ac18_5_5_get_ai_settings_returns_config_defaults(
    client: AsyncClient,
) -> None:
    """AC18.5.5: GET /users/me/settings reflects backend feature-flag defaults on load."""
    response = await client.get("/users/me/settings")

    assert response.status_code == 200
    assert response.json() == {
        "enable_ai_reconciliation": settings.enable_ai_reconciliation,
        "enable_ai_classification": settings.enable_ai_classification,
    }


async def test_ac18_5_5_patch_ai_settings_persists_user_overrides(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC18.5.5: PATCH /users/me/settings persists AI toggle overrides in users.ai_settings."""
    response = await client.patch(
        "/users/me/settings",
        json={"enable_ai_reconciliation": True, "enable_ai_classification": True},
    )

    assert response.status_code == 200
    assert response.json() == {"enable_ai_reconciliation": True, "enable_ai_classification": True}

    await db.refresh(test_user)
    assert test_user.ai_settings == {"enable_ai_reconciliation": True, "enable_ai_classification": True}

    followup = await client.get("/users/me/settings")
    assert followup.status_code == 200
    assert followup.json() == {"enable_ai_reconciliation": True, "enable_ai_classification": True}


async def test_ac18_5_5_patch_ai_settings_preserves_unspecified_values(
    client: AsyncClient,
) -> None:
    """AC18.5.5: partial PATCH only changes supplied AI setting keys."""
    first = await client.patch("/users/me/settings", json={"enable_ai_reconciliation": True})
    assert first.status_code == 200

    second = await client.patch("/users/me/settings", json={"enable_ai_classification": True})
    assert second.status_code == 200
    assert second.json() == {"enable_ai_reconciliation": True, "enable_ai_classification": True}


async def test_ac18_5_5_get_ai_settings_returns_404_for_missing_user(
    public_client: AsyncClient,
) -> None:
    """AC18.5.5: GET /users/me/settings returns 404 when authenticated user row is missing.

    Uses dependency_overrides to bypass the auth-layer existence check and exercise the
    router's own 404 branch (defense-in-depth against deleted-mid-session users).
    """
    from src.auth import get_current_user_id
    from src.main import app

    ghost_id = uuid4()
    app.dependency_overrides[get_current_user_id] = lambda: ghost_id
    try:
        response = await public_client.get("/users/me/settings")
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)

    assert response.status_code == 404


async def test_ac18_5_5_patch_ai_settings_returns_404_for_missing_user(
    public_client: AsyncClient,
) -> None:
    """AC18.5.5: PATCH /users/me/settings returns 404 when authenticated user row is missing."""
    from src.auth import get_current_user_id
    from src.main import app

    ghost_id = uuid4()
    app.dependency_overrides[get_current_user_id] = lambda: ghost_id
    try:
        response = await public_client.patch(
            "/users/me/settings",
            json={"enable_ai_reconciliation": True},
        )
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)

    assert response.status_code == 404


async def test_ac18_5_5_get_ai_settings_reflects_persisted_overrides(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC18.5.5: GET /users/me/settings reflects pre-existing ai_settings overrides."""
    test_user.ai_settings = {"enable_ai_reconciliation": True, "enable_ai_classification": False}
    await db.commit()

    response = await client.get("/users/me/settings")
    assert response.status_code == 200
    assert response.json() == {"enable_ai_reconciliation": True, "enable_ai_classification": False}

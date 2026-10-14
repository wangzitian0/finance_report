"""API tests for EPIC-018 AI user settings endpoints."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, settings
from src.identity import User

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
        "auto_accept_ai_suggestions": settings.auto_accept_ai_suggestions,
    }


async def test_AC_extraction_ai_classification_default_1_new_user_settings_show_classification_on(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-extraction.ai-classification-default.1: a user with no override sees classification on, reconciliation off."""
    monkeypatch.delenv("ENABLE_AI_CLASSIFICATION", raising=False)
    monkeypatch.delenv("ENABLE_AI_RECONCILIATION", raising=False)
    code_defaults = Settings(_env_file=None)
    monkeypatch.setattr(settings, "enable_ai_classification", code_defaults.enable_ai_classification)
    monkeypatch.setattr(settings, "enable_ai_reconciliation", code_defaults.enable_ai_reconciliation)

    response = await client.get("/users/me/settings")

    assert response.status_code == 200
    assert response.json() == {
        "enable_ai_reconciliation": False,
        "enable_ai_classification": True,
        "auto_accept_ai_suggestions": True,
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
    assert response.json() == {
        "enable_ai_reconciliation": True,
        "enable_ai_classification": True,
        "auto_accept_ai_suggestions": True,
    }

    await db.refresh(test_user)
    assert test_user.ai_settings == {"enable_ai_reconciliation": True, "enable_ai_classification": True}

    followup = await client.get("/users/me/settings")
    assert followup.status_code == 200
    assert followup.json() == {
        "enable_ai_reconciliation": True,
        "enable_ai_classification": True,
        "auto_accept_ai_suggestions": True,
    }


async def test_ac18_5_5_patch_ai_settings_preserves_unspecified_values(
    client: AsyncClient,
) -> None:
    """AC18.5.5: partial PATCH only changes supplied AI setting keys."""
    first = await client.patch("/users/me/settings", json={"enable_ai_reconciliation": True})
    assert first.status_code == 200

    second = await client.patch("/users/me/settings", json={"enable_ai_classification": True})
    assert second.status_code == 200
    assert second.json() == {
        "enable_ai_reconciliation": True,
        "enable_ai_classification": True,
        "auto_accept_ai_suggestions": True,
    }


async def test_AC_extraction_auto_accept_1_the_code_default_is_on_and_a_user_can_turn_it_off(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-extraction.auto-accept.1: the system accepts the AI suggestions unless the user says no."""
    monkeypatch.delenv("AUTO_ACCEPT_AI_SUGGESTIONS", raising=False)
    assert Settings(_env_file=None).auto_accept_ai_suggestions is True
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", True)

    default = await client.get("/users/me/settings")
    turned_off = await client.patch("/users/me/settings", json={"auto_accept_ai_suggestions": False})
    followup = await client.get("/users/me/settings")

    assert default.json()["auto_accept_ai_suggestions"] is True
    assert turned_off.status_code == 200
    assert turned_off.json()["auto_accept_ai_suggestions"] is False
    assert followup.json()["auto_accept_ai_suggestions"] is False
    await db.refresh(test_user)
    assert test_user.ai_settings == {"auto_accept_ai_suggestions": False}


async def test_ac18_5_5_get_ai_settings_returns_404_for_missing_user(
    public_client: AsyncClient,
) -> None:
    """AC18.5.5: GET /users/me/settings returns 404 when authenticated user row is missing.

    Uses dependency_overrides to bypass the auth-layer existence check and exercise the
    router's own 404 branch (defense-in-depth against deleted-mid-session users).
    """
    from src.identity import get_current_user_id
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
    from src.identity import get_current_user_id
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
    assert response.json() == {
        "enable_ai_reconciliation": True,
        "enable_ai_classification": False,
        "auto_accept_ai_suggestions": settings.auto_accept_ai_suggestions,
    }

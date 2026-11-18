from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, settings
from src.extraction import effective_reconciliation, reconciliation_enabled
from src.identity import User, get_current_user_id
from src.main import app

pytestmark = pytest.mark.asyncio


async def test_ac18_5_5_and_auto_accept_settings_defaults_and_overrides(
    client: AsyncClient, db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await client.get("/users/me/settings")).json() == {
        "enable_ai_reconciliation": settings.enable_ai_reconciliation,
        "enable_ai_classification": settings.enable_ai_classification,
        "auto_accept_ai_suggestions": True,
        "auto_accept_ai_suggestions_active": settings.auto_accept_ai_suggestions and settings.enable_ai_classification,
    }
    for env in ("ENABLE_AI_CLASSIFICATION", "ENABLE_AI_RECONCILIATION", "AUTO_ACCEPT_AI_SUGGESTIONS"):
        monkeypatch.delenv(env, raising=False)
    defaults = Settings(_env_file=None)
    assert defaults.auto_accept_ai_suggestions is True
    for attr in ("enable_ai_classification", "enable_ai_reconciliation", "auto_accept_ai_suggestions"):
        monkeypatch.setattr(settings, attr, getattr(defaults, attr))
    assert (await client.get("/users/me/settings")).json() == {
        "enable_ai_reconciliation": True,
        "enable_ai_classification": True,
        "auto_accept_ai_suggestions": True,
        "auto_accept_ai_suggestions_active": True,
    }

    p1 = await client.patch("/users/me/settings", json={"enable_ai_reconciliation": True})
    p2 = await client.patch("/users/me/settings", json={"enable_ai_classification": True})
    await db.refresh(test_user)
    assert (p1.status_code, p2.status_code, test_user.ai_settings) == (
        200,
        200,
        {"enable_ai_reconciliation": True, "enable_ai_classification": True},
    )
    assert (
        p2.json()
        == (await client.get("/users/me/settings")).json()
        == {
            "enable_ai_reconciliation": True,
            "enable_ai_classification": True,
            "auto_accept_ai_suggestions": True,
            "auto_accept_ai_suggestions_active": settings.auto_accept_ai_suggestions,
        }
    )

    off = await client.patch("/users/me/settings", json={"auto_accept_ai_suggestions": False})
    await db.refresh(test_user)
    assert (
        off.status_code == 200
        and off.json()["auto_accept_ai_suggestions"] is False
        and test_user.ai_settings["auto_accept_ai_suggestions"] is False
    )


async def test_AC_extraction_auto_accept_1_matrix_and_panel_save(
    client: AsyncClient, db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = [
        (False, {"auto_accept_ai_suggestions": True}, True, False),
        (True, {"auto_accept_ai_suggestions": True, "enable_ai_classification": False}, True, False),
        (True, {"enable_ai_classification": False}, True, False),
        (True, {"auto_accept_ai_suggestions": True}, True, True),
        (True, {}, True, True),
        (True, {"auto_accept_ai_suggestions": False}, False, False),
    ]
    for flag, stored, choice, in_use in cases:
        monkeypatch.setattr(settings, "auto_accept_ai_suggestions", flag)
        test_user.ai_settings = stored
        await db.commit()
        body = (await client.get("/users/me/settings")).json()
        assert (body["auto_accept_ai_suggestions"], body["auto_accept_ai_suggestions_active"]) == (choice, in_use)

    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", True)
    test_user.ai_settings = {"enable_ai_classification": False}
    await db.commit()
    shown = (await client.get("/users/me/settings")).json()
    editable = {
        k: shown[k] for k in ("enable_ai_reconciliation", "enable_ai_classification", "auto_accept_ai_suggestions")
    }
    s1 = (await client.patch("/users/me/settings", json={**editable, "enable_ai_reconciliation": True})).json()
    s2 = (
        await client.patch(
            "/users/me/settings", json={**editable, "enable_ai_reconciliation": True, "enable_ai_classification": True}
        )
    ).json()
    await db.refresh(test_user)
    assert (
        s1["auto_accept_ai_suggestions"],
        s1["auto_accept_ai_suggestions_active"],
        s2["auto_accept_ai_suggestions"],
        s2["auto_accept_ai_suggestions_active"],
        test_user.ai_settings["auto_accept_ai_suggestions"],
    ) == (True, False, True, True, True)


@pytest.mark.parametrize(("method", "body"), [("GET", None), ("PATCH", {"enable_ai_reconciliation": True})])
async def test_ac18_5_5_ai_settings_returns_404_for_missing_user(public_client: AsyncClient, method, body) -> None:
    app.dependency_overrides[get_current_user_id] = uuid4
    try:
        resp = await public_client.request(method, "/users/me/settings", **({"json": body} if body else {}))
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
    assert resp.status_code == 404


async def test_effective_reconciliation_and_reconciliation_enabled_honor_bool_overrides(
    db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "enable_ai_reconciliation", False)
    assert (
        not effective_reconciliation(None)
        and not effective_reconciliation({})
        and not effective_reconciliation({"enable_ai_reconciliation": "yes"})
        and effective_reconciliation({"enable_ai_reconciliation": True})
    )
    test_user.ai_settings = {"enable_ai_reconciliation": True}
    await db.commit()
    assert await reconciliation_enabled(db, test_user.id) is True
    monkeypatch.setattr(settings, "enable_ai_reconciliation", True)
    test_user.ai_settings = {"enable_ai_reconciliation": False}
    await db.commit()
    assert await reconciliation_enabled(db, test_user.id) is False

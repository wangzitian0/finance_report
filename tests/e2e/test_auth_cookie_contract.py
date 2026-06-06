"""E2E auth fixture contract tests."""

import pytest

from conftest import TestConfig, auth_cookie


@pytest.mark.smoke
def test_auth_cookie_uses_domain_path_for_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(TestConfig, "APP_URL", "https://report-pr-740.zitian.party")

    cookie = auth_cookie("test-token")

    assert cookie == {
        "name": "finance_access_token",
        "value": "test-token",
        "domain": "report-pr-740.zitian.party",
        "path": "/",
        "httpOnly": True,
        "sameSite": "Lax",
        "secure": True,
    }


@pytest.mark.smoke
def test_auth_cookie_does_not_force_secure_for_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(TestConfig, "APP_URL", "http://localhost:3000")

    cookie = auth_cookie("test-token")

    assert cookie == {
        "name": "finance_access_token",
        "value": "test-token",
        "domain": "localhost",
        "path": "/",
        "httpOnly": True,
        "sameSite": "Lax",
    }

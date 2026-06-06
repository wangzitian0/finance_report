"""AC8.13.50: E2E fixture auth cookies stay compatible with Playwright."""

import pytest

from tests.e2e.auth_cookie import build_auth_cookie


def test_AC8_13_50_auth_cookie_uses_domain_path_for_preview() -> None:
    cookie = build_auth_cookie("https://report-pr-740.zitian.party", "test-token")

    assert cookie == {
        "name": "finance_access_token",
        "value": "test-token",
        "domain": "report-pr-740.zitian.party",
        "path": "/",
        "httpOnly": True,
        "sameSite": "Lax",
        "secure": True,
    }


def test_AC8_13_50_auth_cookie_does_not_force_secure_for_localhost() -> None:
    cookie = build_auth_cookie("http://localhost:3000", "test-token")

    assert cookie == {
        "name": "finance_access_token",
        "value": "test-token",
        "domain": "localhost",
        "path": "/",
        "httpOnly": True,
        "sameSite": "Lax",
    }


def test_AC8_13_50_auth_cookie_rejects_app_url_without_hostname() -> None:
    with pytest.raises(ValueError, match="APP_URL must include a hostname"):
        build_auth_cookie("not-a-url", "test-token")

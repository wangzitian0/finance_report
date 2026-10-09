"""AC8.13.50: E2E fixture auth cookies stay compatible with Playwright."""

import pytest

from tests.e2e.auth_cookie import build_auth_cookie, build_runner_browser_session


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


def test_AC8_13_50_runner_browser_session_builds_cookie_and_storage_script() -> None:
    app_url = "https://report-pr-740.zitian.party"
    cookie, script = build_runner_browser_session(
        {
            "user_email": "qa@test.example.com",
            "user_data": {"access_token": "tok", "id": "42"},
        },
        app_url,
    )

    assert cookie == build_auth_cookie(app_url, "tok")
    assert "localStorage.setItem('finance_user_id', \"42\");" in script
    assert (
        "localStorage.setItem('finance_user_email', \"qa@test.example.com\");" in script
    )


def test_AC8_13_50_runner_browser_session_reads_nested_user_id() -> None:
    _, script = build_runner_browser_session(
        {
            "user_email": "qa@test.example.com",
            "user_data": {"access_token": "tok", "user": {"id": 7}},
        },
        "http://localhost:3000",
    )

    assert "localStorage.setItem('finance_user_id', \"7\");" in script


@pytest.mark.parametrize(
    "auth_context",
    [
        {"user_email": "qa@test.example.com", "user_data": {"id": "1"}},
        {"user_email": "qa@test.example.com", "user_data": {"access_token": "tok"}},
        {"user_data": {"access_token": "tok", "id": "1"}},
        {},
    ],
    ids=["no-token", "no-user-id", "no-email", "empty"],
)
def test_AC8_13_50_runner_browser_session_rejects_incomplete_context(
    auth_context: dict,
) -> None:
    with pytest.raises(
        ValueError, match="Invalid auth context for browser session injection"
    ):
        build_runner_browser_session(auth_context, "http://localhost:3000")

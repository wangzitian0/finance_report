from __future__ import annotations

import re
import uuid

import pytest
from playwright.async_api import Page, expect

from tests.e2e._journey_helpers import assert_pinned_via_page, get_url
from tests.e2e.deployment_pin import expected_version_from_env

AUTH_LANDING_URL_PATTERN = re.compile("/(?:dashboard)?(?:[?#].*)?$")


async def _fill_and_submit_auth(
    page: Page,
    *,
    email: str,
    password: str,
    button: str,
    endpoint: str,
    expected_status: int,
) -> None:
    await page.get_by_label("Email").fill(email)
    await page.get_by_label("Password", exact=True).fill(password)
    async with page.expect_response(
        lambda r: r.url.endswith(endpoint) and r.request.method == "POST"
    ) as resp:
        await page.get_by_role("button", name=button, exact=True).click()
    assert (await resp.value).status == expected_status


async def _assert_auth_api_path(
    page: Page, *, register: bool, email: str, button_name: str, expected_path: str
) -> None:
    await page.goto(get_url("/login"))
    if register:
        await expect(page.locator("h1")).to_contain_text("Finance Report")
        await page.get_by_test_id("auth-mode-toggle-register").click()
    await page.get_by_label("Email").fill(email)
    await page.get_by_label("Password", exact=True).fill("TestPassword123!")
    captured: list[str] = []
    page.on(
        "request",
        lambda req: captured.append(req.url) if expected_path in req.url else None,
    )
    await page.get_by_role("button", name=button_name).click()
    await page.wait_for_timeout(2000)
    assert (
        captured
        and "/api/api/" not in captured[-1]
        and (
            f"/api/{expected_path}" in captured[-1]
            or f"/{expected_path}" in captured[-1]
        )
    ), f"Unexpected API path: {captured}"


async def test_registration_api_path(page: Page) -> None:
    await _assert_auth_api_path(
        page,
        register=True,
        email=f"e2e_test_{uuid.uuid4().hex[:8]}@test.local",
        button_name="Create Account",
        expected_path="auth/register",
    )


async def test_login_api_path(page: Page) -> None:
    await _assert_auth_api_path(
        page,
        register=False,
        email="test@example.com",
        button_name="Login",
        expected_path="auth/login",
    )


async def test_full_registration_flow(page: Page) -> None:
    await page.goto(get_url("/login"))
    await page.get_by_test_id("auth-mode-toggle-register").click()
    await page.get_by_label("Email").fill(f"e2e_full_{uuid.uuid4().hex[:8]}@test.local")
    await page.get_by_label("Password", exact=True).fill("SecureTestPass123!")
    await page.get_by_role("button", name="Create Account").click()
    try:
        await expect(page).to_have_url(AUTH_LANDING_URL_PATTERN, timeout=10000)
        await expect(page.get_by_role("button", name="Logout")).to_be_visible(
            timeout=10000
        )
    except AssertionError:
        err = page.locator(".text-red-500, [class*='error']").first
        if await err.count() > 0:
            err_text = await err.text_content() or ""
            assert "Not Found" not in err_text
            pytest.fail(f"Registration failed with: {err_text}")
        raise


@pytest.mark.parametrize("viewport", ["desktop", "mobile"])
async def test_browser_cookie_logout_lifecycle(
    page: Page, viewport: str, record_property
) -> None:
    expected = expected_version_from_env()
    assert expected, "Authentication lifecycle proof requires explicit EXPECTED_SHA or APP_VERSION_REF"
    await assert_pinned_via_page(page, record_property)
    await page.set_viewport_size(
        {"width": 390, "height": 844}
        if viewport == "mobile"
        else {"width": 1280, "height": 900}
    )
    email, password = (
        f"e2e_logout_{uuid.uuid4().hex[:10]}@test.example.com",
        "SyntheticBrowserLogout123!",
    )
    await page.goto(get_url("/login"))
    await page.get_by_test_id("auth-mode-toggle-register").click()
    await _fill_and_submit_auth(
        page,
        email=email,
        password=password,
        button="Create Account",
        endpoint="/api/auth/register",
        expected_status=201,
    )
    await expect(page).to_have_url(AUTH_LANDING_URL_PATTERN)
    assert (await page.request.get(get_url("/api/auth/me"))).status == 200
    await page.reload()
    await expect(page.get_by_role("link", name="Finance Report home")).to_be_attached()
    assert (await page.request.get(get_url("/api/auth/me"))).status == 200
    if viewport == "mobile":
        await page.get_by_role("link", name="More", exact=True).click()
    async with page.expect_response(
        lambda r: r.url.endswith("/api/auth/logout") and r.request.method == "POST"
    ) as out:
        await page.get_by_role("button", name="Logout", exact=True).click()
    assert (await out.value).status == 204
    await expect(page).to_have_url(re.compile("/login$"))
    assert (
        (await page.request.get(get_url("/api/auth/me"))).status == 401
        and all(
            c["name"] != "finance_access_token" for c in await page.context.cookies()
        )
        and await page.evaluate("localStorage.getItem('finance_user_id')") is None
    )
    await page.reload()
    await expect(page).to_have_url(re.compile("/login$"))
    assert (await page.request.get(get_url("/api/auth/me"))).status == 401
    await _fill_and_submit_auth(
        page,
        email=email,
        password=password,
        button="Sign In",
        endpoint="/api/auth/login",
        expected_status=200,
    )
    await expect(page).to_have_url(AUTH_LANDING_URL_PATTERN)
    assert (await page.request.get(get_url("/api/auth/me"))).status == 200
    record_property("browser_logout_viewport", viewport)


@pytest.mark.e2e
async def test_registration_flow(page: Page) -> None:
    await page.goto(get_url("/login"))
    await expect(page.locator("body")).to_be_visible()
    await page.get_by_role("button", name="Register").first.click()
    await page.get_by_label("Email Address").fill(
        f"e2e-test-{uuid.uuid4().hex[:8]}@example.com"
    )
    await page.get_by_label("Password", exact=True).fill("TestPassword123!")
    async with page.expect_response("**/api/auth/register") as resp_info:
        await page.get_by_role("button", name="Create Account").click()
    resp = await resp_info.value
    assert resp.status in (200, 201) and {"id", "access_token"} <= set(
        await resp.json()
    )
    await expect(page).to_have_url(AUTH_LANDING_URL_PATTERN, timeout=10000)
    await expect(page.get_by_role("button", name="Logout")).to_be_visible(timeout=10000)

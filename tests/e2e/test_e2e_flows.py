"""
End-to-End Functional Flow Tests (Finance Report).

Covers:
- Scenario 1: Basic UI Navigation & Loading.
- Scenario 2: Statement Upload, Parsing (LLM simulation), and Cleanup.
- Scenario 3: Report Generation View.
- Scenario 4: Reconciliation Match Approval.
- Scenario 5: Account/Journal Entry lifecycle.
"""

import os
import sys
import pytest
import subprocess
from pathlib import Path
from playwright.async_api import Page, expect

# --- Configuration ---

APP_URL = os.getenv("APP_URL", "http://localhost:3000")
PARSING_TIMEOUT = 60000  # LLM parsing can be slow
EXPECTED_TXN_COUNT = 15


def get_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}{path}"


# --- Fixtures ---


@pytest.fixture(autouse=True)
async def setup_e2e(page: Page):
    """Common setup for all E2E tests."""
    # Could handle login here if implemented
    pass


# --- Tests ---


@pytest.mark.smoke
@pytest.mark.e2e
async def test_full_navigation(page: Page):
    """[Scenario 1] Verify all main pages load or redirect to login."""
    pages = [
        "/dashboard",
        "/accounts",
        "/journal",
        "/statements",
        "/reconciliation",
        "/reports",
    ]

    for path in pages:
        await page.goto(get_url(path))

        # Wait a moment for potential AuthGuard redirect
        try:
            await page.wait_for_url("**/login", timeout=3000)
        except:
            pass

        # Since we are not logged in, we expect either the page or a redirect to login
        # We check that the body is visible and we didn't hit a 500 error.
        await expect(page.locator("body")).to_be_visible()

        content = await page.content()
        # Allow being on the login page as a successful "protection" check
        if "/login" in page.url:
            continue

        # If not redirected, ensure no 404 or 500
        assert "404" not in content and "page not found" not in content.lower()
        assert "Internal Server Error" not in content


@pytest.mark.e2e
async def test_statement_upload_parsing_flow(page: Page, tmp_path):
    """
    [Scenario 2] Upload a statement, wait for parsing, and then delete it.
    Uses the generate_pdf_fixtures.py script to create a real PDF.
    """
    # 0. Preparation: Locate PDF fixture generator
    root_dir = Path(__file__).parent.parent.parent
    script_path = root_dir / "scripts" / "generate_pdf_fixtures.py"
    # Fallback to older path if not found at root (some PRs move it)
    if not script_path.exists():
        script_path = root_dir / "scripts" / "pdf_fixtures" / "generate_pdf_fixtures.py"

    output_dir = tmp_path

    # 1. Generate PDF
    cmd = [sys.executable, str(script_path), str(output_dir)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        pytest.skip(
            f"Failed to generate PDF fixture: {e.stderr}. Ensure reportlab is installed."
        )

    target_pdf = output_dir / "e2e_dbs_statement.pdf"
    if not target_pdf.exists():
        pytest.fail(f"Generated PDF not found at {target_pdf}")

    try:
        # 2. Upload
        await page.goto(get_url("/statements"))

        # Wait for redirect or check if we are on login
        if "/login" in page.url:
            pytest.skip("Redirected to login - auth not configured for E2E")

        await page.get_by_label("Bank / Institution").fill("DBS E2E Test")
        await page.set_input_files("input[type='file']", str(target_pdf))

        # 3. Click Upload
        async with page.expect_response("**/api/statements/upload"):
            await page.get_by_role("button", name="Upload & Parse Statement").click()

        # 4. Verify List
        await expect(page.get_by_text("DBS E2E Test").first).to_be_visible()

        # 5. Wait for Parsing
        row = page.locator("a", has=page.get_by_text("DBS E2E Test")).first
        await expect(row).to_contain_text(
            f"{EXPECTED_TXN_COUNT} txns", timeout=PARSING_TIMEOUT
        )
        await expect(row).to_contain_text("parsed", ignore_case=True)

    finally:
        # 6. Cleanup
        row = page.locator("a", has=page.get_by_text("DBS E2E Test")).first
        if await row.count() > 0:
            page.once("dialog", lambda dialog: dialog.accept())
            await row.get_by_title("Delete Statement").click()
            await expect(page.get_by_text("DBS E2E Test")).not_to_be_visible()


@pytest.mark.e2e
async def test_reports_view(page: Page):
    """[Scenario 3] Reports Page renders or redirects to login."""
    await page.goto(get_url("/reports"))

    # Wait a moment for potential AuthGuard redirect
    try:
        await page.wait_for_url("**/login", timeout=3000)
    except:
        pass

    if "/login" in page.url:
        # If redirected to login, verify login page basic visibility
        await expect(page.locator("body")).to_be_visible()
        return

    await expect(page.get_by_text("Balance Sheet", exact=False).first).to_be_visible()


@pytest.mark.e2e
async def test_account_deletion_constraint(page: Page):
    """[Scenario 5] Account Deletion Constraints (Negative Test)."""
    await page.goto(get_url("/accounts"))

    # Wait for redirect if not logged in
    try:
        await page.wait_for_url("**/login", timeout=3000)
    except:
        pass

    if "/login" in page.url:
        pytest.skip("Skipping functional account test - redirected to login")

    try:
        await page.get_by_role("button", name="Add Account").click()
        await page.fill("input[placeholder='Account Name']", "E2E Constraint Test")
        await page.select_option("select", label="ASSET")
        await page.get_by_role("button", name="Create Account").click()

        await expect(page.get_by_text("E2E Constraint Test")).to_be_visible()

        # UI flow for deletion constraint validation (with Journal Entry) is complex
        # and currently under development for E2E.
        pytest.skip(
            "Full account deletion constraint UI flow not fully implemented in E2E yet"
        )

    finally:
        # Cleanup
        await page.goto(get_url("/accounts"))
        row = page.locator("div", has=page.get_by_text("E2E Constraint Test")).first
        if await row.count() > 0:
            page.once("dialog", lambda dialog: dialog.accept())
            await row.get_by_title("Delete Account").click()


@pytest.mark.e2e
async def test_registration_flow(page: Page):
    """
    [Scenario 6] User Registration Flow.
    Verifies that the API URL configuration is correct (no double /api/ issue).
    """
    import uuid

    await page.goto(get_url("/login"))

    # Verify we are on the login page
    await expect(page.locator("body")).to_be_visible()

    # Switch to Register tab
    await page.get_by_role("button", name="Register").click()

    # Generate unique email for this test
    unique_email = f"e2e-test-{uuid.uuid4().hex[:8]}@example.com"
    test_password = "TestPassword123!"

    # Fill registration form
    await page.get_by_label("Email Address").fill(unique_email)
    await page.get_by_label("Password").fill(test_password)

    # Submit and wait for response
    async with page.expect_response("**/api/auth/register") as response_info:
        await page.get_by_role("button", name="Create Account").click()

    response = await response_info.value

    # Verify successful registration (201 or 200 depending on implementation)
    assert response.status in [200, 201], (
        f"Registration failed with status {response.status}"
    )

    # Verify response contains user data (id and email)
    response_data = await response.json()
    assert "id" in response_data, "Response should contain user id"
    assert "access_token" in response_data, "Response should contain access token"

    # Verify we were redirected to dashboard
    await page.wait_for_url("**/dashboard", timeout=5000)
    assert "/dashboard" in page.url, "Should redirect to dashboard after registration"

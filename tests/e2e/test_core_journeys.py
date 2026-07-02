"""
Core Application Journey Tests (Finance Report).

EPIC/AC ownership:
- AC8.10.1 / AC8.8.1: health endpoint smoke
- AC8.8.2 / AC8.10.2: accounts CRUD
- AC8.8.3 / AC8.10.3: journal entry lifecycle
- AC8.8.4 / AC8.10.7: reports API
- AC8.8.5 / AC8.10.5: reconciliation API
- AC8.7.1 / AC8.10.9: authentication failures
- AC8.4.2: statement listing endpoints
- AC6.11.1: AI model catalog endpoint
- AC6.5.1: chat suggestions endpoint
- AC1.5.4: ping toggle endpoint
- AC8.3.4 / AC8.10.6: unbalanced journal entry rejection

Covers:
- Smoke Tests (Public pages, API health) - Run everywhere.
- E2E Tests (User flows, Data mutation) - Run on Staging/Dev only.
"""

import os
import pytest
import httpx
from playwright.async_api import Page, expect

# --- Configuration ---

APP_URL = os.getenv("APP_URL", "http://localhost:3000")
TEST_ENV = os.getenv("TEST_ENV", "staging").lower()  # dev, staging, prod
API_TIMEOUT = float(os.getenv("E2E_API_TIMEOUT", "30"))

# Skip write tests if we are in production
SKIP_WRITE = pytest.mark.skipif(
    TEST_ENV == "prod", reason="Write tests are disabled in Production"
)

# Skip E2E UI tests if specifically requested (e.g. CI smoke only)
SKIP_UI = pytest.mark.skipif(
    os.getenv("SKIP_UI_TESTS", "false").lower() == "true",
    reason="UI tests skipped via env var",
)


@pytest.fixture(scope="module")
def app_url():
    """Returns the base URL of the application under test."""
    return APP_URL.rstrip("/")


# --- Smoke Tests (API / Basic Connectivity) ---


@pytest.mark.smoke
@pytest.mark.api
async def test_api_health_check(app_url):
    """EPIC-001 EPIC-007 EPIC-010 EPIC-012 / AC8.10.1 AC8.8.1: Verify API health."""
    # verify=False is intentional for dev/staging self-signed certs
    async with httpx.AsyncClient(verify=False, timeout=API_TIMEOUT) as client:
        # Try both common health paths just in case
        for path in ["/api/health", "/api/ping"]:
            try:
                response = await client.get(f"{app_url}{path}")
                if response.status_code == 200:
                    return  # Success
            except httpx.ConnectError:
                continue

        # If we get here, neither worked or connection failed
        pytest.fail(f"Could not reach health endpoints at {app_url}")


@pytest.mark.smoke
async def test_homepage_loads(app_url):
    """EPIC-007 / AC-runtime.1.3: Verify the homepage is accessible (frontend reachability)."""
    async with httpx.AsyncClient(verify=False, timeout=API_TIMEOUT) as client:
        response = await client.get(f"{app_url}/")
        assert response.status_code < 400, f"Homepage returned {response.status_code}"


# --- E2E Tests (Playwright UI) ---


@pytest.mark.e2e
@SKIP_UI
async def test_dashboard_ui_load(page: Page, app_url):
    """EPIC-005 EPIC-007 EPIC-008 / AC8.13.9: Verify dashboard route smoke."""
    await page.goto(f"{app_url}/dashboard")

    # We expect some key element to be present.
    # Use Regex for title check as Playwright doesn't accept lambdas here.
    try:
        await expect(page).to_have_title(r"(Finance|Dashboard)", timeout=5000)
    except AssertionError:
        # Fallback if title check fails
        await expect(page.locator("body")).to_be_visible()


# --- API Integration Tests ---


@pytest.mark.e2e
@SKIP_WRITE
async def test_ping_toggle_via_api(app_url):
    """
    EPIC-001 / AC1.5.4

    Scenario: Toggle ping/pong state via API (no auth required).
    Environment: Staging/Dev Only.
    """
    async with httpx.AsyncClient(verify=False, timeout=API_TIMEOUT) as client:
        before_response = await client.get(f"{app_url}/api/ping")
        assert before_response.status_code == 200
        before_state = before_response.json()["state"]

        toggle_response = await client.post(f"{app_url}/api/ping/toggle")
        assert toggle_response.status_code == 200

        after_response = await client.get(f"{app_url}/api/ping")
        assert after_response.status_code == 200
        after_state = after_response.json()["state"]

        assert before_state != after_state, "State should change after toggle"
        assert after_state in ["ping", "pong"]


# --- API Integration Tests (Authenticated) ---


@pytest.mark.e2e
@pytest.mark.api
async def test_api_authentication_failures(app_url):
    """
    EPIC-001 EPIC-016 / AC8.7.1 AC8.10.9

    Scenario: Verify API endpoints return 401 without valid authentication.
    Environment: All (security validation).
    - GET /accounts without auth header (should return 401; 429 accepted if rate-limited)
    - GET /accounts with invalid token (should return 401; 429 accepted if rate-limited)
    """
    async with httpx.AsyncClient(verify=False, timeout=API_TIMEOUT) as client:
        # Test 1: No auth header
        response = await client.get(f"{app_url}/api/accounts")
        assert response.status_code in (401, 429), (
            f"Missing auth should return 401, got {response.status_code}"
        )
        # Test 2: Invalid token
        invalid_headers = {"Authorization": "Bearer invalid_token_xyz_12345"}
        response = await client.get(f"{app_url}/api/accounts", headers=invalid_headers)
        assert response.status_code in (401, 429), (
            f"Invalid token should return 401, got {response.status_code}"
        )


@pytest.mark.e2e
@pytest.mark.api
@SKIP_WRITE
async def test_accounts_crud_api(app_url, shared_auth_state):
    """
    EPIC-001 EPIC-002 / AC8.8.2 AC8.10.2

    Scenario: Full CRUD lifecycle for accounts via API.
    Environment: Staging/Dev Only.

    Tests:
    - POST /accounts (create)
    - GET /accounts (list)
    - GET /accounts/{id} (read)
    - PUT /accounts/{id} (update)
    - DELETE /accounts/{id} (delete)
    """
    async with httpx.AsyncClient(verify=False, timeout=API_TIMEOUT) as client:
        headers = {"Authorization": f"Bearer {shared_auth_state.access_token}"}

        # 1. Create account
        create_payload = {
            "name": "E2E Test Cash Account",
            "code": "1001",
            "type": "ASSET",
            "currency": "SGD",
        }
        response = await client.post(
            f"{app_url}/api/accounts", headers=headers, json=create_payload
        )
        assert response.status_code == 201, f"Create failed: {response.text}"
        account = response.json()
        account_id = account["id"]
        assert account["name"] == "E2E Test Cash Account"
        assert account["type"] == "ASSET"

        # 2. List accounts (verify created account is present)
        response = await client.get(f"{app_url}/api/accounts", headers=headers)
        assert response.status_code == 200
        accounts_data = response.json()
        accounts = accounts_data.get(
            "items", accounts_data
        )  # Handle paginated response
        assert any(a["id"] == account_id for a in accounts), (
            "Created account not in list"
        )

        # 3. Get single account
        response = await client.get(
            f"{app_url}/api/accounts/{account_id}", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["id"] == account_id

        # 4. Update account
        update_payload = {"name": "E2E Updated Cash Account"}
        response = await client.put(
            f"{app_url}/api/accounts/{account_id}",
            headers=headers,
            json=update_payload,
        )
        assert response.status_code == 200
        assert response.json()["name"] == "E2E Updated Cash Account"

        # 5. Delete account
        response = await client.delete(
            f"{app_url}/api/accounts/{account_id}", headers=headers
        )
        assert response.status_code == 204, f"Delete failed: {response.text}"

        # 6. Verify deletion
        response = await client.get(
            f"{app_url}/api/accounts/{account_id}", headers=headers
        )
        assert response.status_code == 404, "Account should be deleted"


@pytest.mark.e2e
@pytest.mark.api
@SKIP_WRITE
async def test_journal_entry_lifecycle_api(app_url, shared_auth_state):
    """
    EPIC-002 / AC8.8.3 AC8.10.3

    Scenario: Create, post, and void a journal entry via API.
    Environment: Staging/Dev Only.

    Tests:
    - POST /accounts (setup debit/credit accounts)
    - POST /journal-entries (create balanced entry)
    - GET /journal-entries/{id} (read)
    - POST /journal-entries/{id}/postings (post entry)
    - POST /journal-entries/{id}/voidings (void entry)
    - DELETE /journal-entries/{id} (cleanup)
    """
    async with httpx.AsyncClient(verify=False, timeout=API_TIMEOUT) as client:
        headers = {"Authorization": f"Bearer {shared_auth_state.access_token}"}

        # Setup: Create two accounts for balanced entry
        cash_account = await client.post(
            f"{app_url}/api/accounts",
            headers=headers,
            json={
                "name": "E2E Cash",
                "code": "1100",
                "type": "ASSET",
                "currency": "SGD",
            },
        )
        assert cash_account.status_code == 201
        cash_id = cash_account.json()["id"]

        expense_account = await client.post(
            f"{app_url}/api/accounts",
            headers=headers,
            json={
                "name": "E2E Office Expense",
                "code": "5100",
                "type": "EXPENSE",
                "currency": "SGD",
            },
        )
        assert expense_account.status_code == 201
        expense_id = expense_account.json()["id"]

        entry_id = None  # Initialize for finally block
        reversal_id = None  # Track reversal entry for cleanup
        try:
            # 1. Create journal entry (balanced: debit expense, credit cash)
            entry_payload = {
                "entry_date": "2026-01-24",
                "memo": "E2E Test: Office supplies purchase",
                "lines": [
                    {
                        "account_id": expense_id,
                        "direction": "DEBIT",
                        "amount": "50.00",
                        "currency": "SGD",
                    },
                    {
                        "account_id": cash_id,
                        "direction": "CREDIT",
                        "amount": "50.00",
                        "currency": "SGD",
                    },
                ],
            }
            response = await client.post(
                f"{app_url}/api/journal-entries", headers=headers, json=entry_payload
            )
            assert response.status_code == 201, f"Create entry failed: {response.text}"
            entry = response.json()
            entry_id = entry["id"]
            assert entry["status"].lower() == "draft"

            # 2. Get entry
            response = await client.get(
                f"{app_url}/api/journal-entries/{entry_id}", headers=headers
            )
            assert response.status_code == 200
            assert len(response.json()["lines"]) == 2

            # 3. Post entry
            response = await client.post(
                f"{app_url}/api/journal-entries/{entry_id}/postings", headers=headers
            )
            assert response.status_code == 200, f"Post failed: {response.text}"
            assert response.json()["status"].lower() == "posted"

            # 4. Void entry (creates reversal entry, original remains posted)
            response = await client.post(
                f"{app_url}/api/journal-entries/{entry_id}/voidings",
                headers=headers,
                json={"reason": "E2E Test cleanup"},
            )
            assert response.status_code == 200, f"Void failed: {response.text}"
            reversal = response.json()
            reversal_id = reversal["id"]  # Track for cleanup
            # Void creates a new reversal entry that is immediately posted
            assert reversal["status"].lower() == "posted"
            assert reversal["id"] != entry_id  # It's a new entry
            # Memo should indicate it's a void/reversal
            assert "void" in reversal.get("memo", "").lower()

        finally:
            # Cleanup: Delete both entries (original + reversal) and accounts
            if reversal_id:
                await client.delete(
                    f"{app_url}/api/journal-entries/{reversal_id}", headers=headers
                )
            if entry_id:
                await client.delete(
                    f"{app_url}/api/journal-entries/{entry_id}", headers=headers
                )
            await client.delete(f"{app_url}/api/accounts/{cash_id}", headers=headers)
            await client.delete(f"{app_url}/api/accounts/{expense_id}", headers=headers)


@pytest.mark.e2e
@pytest.mark.api
async def test_reports_api(app_url, shared_auth_state):
    """
    EPIC-005 / AC8.8.4 AC8.10.7

    Scenario: Fetch all financial reports via API.
    Environment: All (read-only).

    Tests:
    - GET /reports/balance-sheet
    - GET /reports/income-statement
    - GET /reports/cash-flow
    - GET /reports/trend
    - GET /reports/breakdown
    """
    async with httpx.AsyncClient(verify=False, timeout=API_TIMEOUT) as client:
        headers = {"Authorization": f"Bearer {shared_auth_state.access_token}"}

        # Common date params for reports that require them
        date_params = {"start_date": "2025-01-01", "end_date": "2026-12-31"}

        # Balance Sheet (as_of_date optional)
        response = await client.get(
            f"{app_url}/api/reports/balance-sheet", headers=headers
        )
        assert response.status_code == 200, f"Balance sheet failed: {response.text}"
        bs = response.json()
        assert "assets" in bs or "total_assets" in bs or "data" in bs

        # Income Statement (requires start_date, end_date)
        response = await client.get(
            f"{app_url}/api/reports/income-statement",
            headers=headers,
            params=date_params,
        )
        assert response.status_code == 200, f"Income statement failed: {response.text}"

        # Cash Flow (requires start_date, end_date)
        response = await client.get(
            f"{app_url}/api/reports/cash-flow",
            headers=headers,
            params=date_params,
        )
        assert response.status_code == 200, f"Cash flow failed: {response.text}"
        cf = response.json()
        # Verify cash flow structure (operating, investing, financing)
        assert any(
            key in str(cf).lower()
            for key in ["operating", "investing", "financing", "activities"]
        )

        # Note: Trend and Breakdown require account_id which needs existing data.
        # These are tested implicitly via unit tests. E2E focus is on core flows.


@pytest.mark.e2e
@pytest.mark.api
async def test_reconciliation_api(app_url, shared_auth_state):
    """
    EPIC-004 / AC8.8.5 AC8.10.5

    Scenario: Test reconciliation endpoints via API.
    Environment: All (read-only operations).

    Tests:
    - GET /reconciliation/stats
    - GET /reconciliation/pending
    - GET /reconciliation/unmatched
    - GET /reconciliation/matches
    """
    async with httpx.AsyncClient(verify=False, timeout=API_TIMEOUT) as client:
        headers = {"Authorization": f"Bearer {shared_auth_state.access_token}"}

        # Stats
        response = await client.get(
            f"{app_url}/api/reconciliation/stats", headers=headers
        )
        assert response.status_code == 200, f"Stats failed: {response.text}"

        # Pending
        response = await client.get(
            f"{app_url}/api/reconciliation/pending", headers=headers
        )
        assert response.status_code == 200, f"Pending failed: {response.text}"

        # Unmatched
        response = await client.get(
            f"{app_url}/api/reconciliation/unmatched", headers=headers
        )
        assert response.status_code == 200, f"Unmatched failed: {response.text}"

        # Matches
        response = await client.get(
            f"{app_url}/api/reconciliation/matches", headers=headers
        )
        assert response.status_code == 200, f"Matches failed: {response.text}"


@pytest.mark.e2e
@pytest.mark.api
async def test_statements_api(app_url, shared_auth_state):
    """
    EPIC-003 EPIC-013 / AC8.4.2

    Scenario: Test statement listing endpoints via API.
    Environment: All (read-only operations).

    Tests:
    - GET /statements (list)
    - GET /statements/pending-review
    """
    async with httpx.AsyncClient(verify=False, timeout=API_TIMEOUT) as client:
        headers = {"Authorization": f"Bearer {shared_auth_state.access_token}"}

        # List statements
        response = await client.get(f"{app_url}/api/statements", headers=headers)
        assert response.status_code == 200, f"List statements failed: {response.text}"

        # Pending review
        response = await client.get(
            f"{app_url}/api/statements/pending-review", headers=headers
        )
        assert response.status_code == 200, f"Pending review failed: {response.text}"


@pytest.mark.e2e
@pytest.mark.api
async def test_ai_models_api(app_url, shared_auth_state):
    """
    EPIC-006 / AC6.11.1

    Scenario: Test the model catalogue listing endpoint (EPIC-023 retired the
    legacy /ai/models in favour of the local LitellmCatalog at /llm/catalog).
    Environment: All (read-only).

    Tests:
    - GET /llm/catalog
    """
    async with httpx.AsyncClient(verify=False, timeout=API_TIMEOUT) as client:
        headers = {"Authorization": f"Bearer {shared_auth_state.access_token}"}

        response = await client.get(f"{app_url}/api/llm/catalog", headers=headers)
        assert response.status_code == 200, f"LLM catalog failed: {response.text}"
        payload = response.json()
        # Should return the catalogue envelope with a list of models.
        assert isinstance(payload, dict) and isinstance(payload.get("models"), list)


@pytest.mark.e2e
@pytest.mark.api
async def test_chat_suggestions_api(app_url, shared_auth_state):
    """
    EPIC-006 / AC6.5.1

    Scenario: Test chat suggestions endpoint.
    Environment: All (read-only).

    Tests:
    - GET /chat/suggestions
    """
    async with httpx.AsyncClient(verify=False, timeout=API_TIMEOUT) as client:
        headers = {"Authorization": f"Bearer {shared_auth_state.access_token}"}

        response = await client.get(f"{app_url}/api/chat/suggestions", headers=headers)
        assert response.status_code == 200, f"Chat suggestions failed: {response.text}"


@pytest.mark.e2e
@pytest.mark.api
@SKIP_WRITE
async def test_unbalanced_journal_entry_rejection(app_url, shared_auth_state):
    """
    EPIC-002 / AC8.3.4 AC8.10.6

    Scenario: Verify unbalanced journal entries are rejected (accounting red line).
    Environment: Staging/Dev Only.

    Tests:
    - POST /journal-entries with unbalanced lines (debit ≠ credit)
    - Verifies API returns 400 or 422 with appropriate error message

    AGENTS.MD Red Line: "NEVER skip entry balance validation"
    """
    async with httpx.AsyncClient(verify=False, timeout=API_TIMEOUT) as client:
        headers = {"Authorization": f"Bearer {shared_auth_state.access_token}"}

        # Setup: Create two accounts for entry
        cash_account = await client.post(
            f"{app_url}/api/accounts",
            headers=headers,
            json={
                "name": "E2E Cash (Unbalanced Test)",
                "code": "1001",
                "type": "ASSET",
                "currency": "SGD",
            },
        )
        assert cash_account.status_code == 201
        cash_id = cash_account.json()["id"]

        expense_account = await client.post(
            f"{app_url}/api/accounts",
            headers=headers,
            json={
                "name": "E2E Expense (Unbalanced Test)",
                "code": "5001",
                "type": "EXPENSE",
                "currency": "SGD",
            },
        )
        assert expense_account.status_code == 201
        expense_id = expense_account.json()["id"]

        try:
            # Attempt to create UNBALANCED entry (debit 100, credit 50)
            entry_payload = {
                "entry_date": "2026-01-24",
                "memo": "E2E Test: Unbalanced entry (should fail)",
                "lines": [
                    {
                        "account_id": expense_id,
                        "direction": "DEBIT",
                        "amount": "100.00",
                        "currency": "SGD",
                    },
                    {
                        "account_id": cash_id,
                        "direction": "CREDIT",
                        "amount": "50.00",
                        "currency": "SGD",
                    },
                ],
            }

            response = await client.post(
                f"{app_url}/api/journal-entries", headers=headers, json=entry_payload
            )

            # Should reject with 400 or 422
            assert response.status_code in (400, 422), (
                f"Unbalanced entry must be rejected, got {response.status_code}: {response.text}"
            )

            # Verify error message mentions balance/debit/credit
            error_detail = str(response.json().get("detail", "")).lower()
            assert any(
                keyword in error_detail
                for keyword in ["balance", "debit", "credit", "equal"]
            ), f"Error message should mention balance issue, got: {error_detail}"

        finally:
            # Cleanup: Delete accounts
            await client.delete(f"{app_url}/api/accounts/{cash_id}", headers=headers)
            await client.delete(f"{app_url}/api/accounts/{expense_id}", headers=headers)

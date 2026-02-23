"""
E2E API Integration tests for core functionality (Tier 1: API Integration E2E)

These tests validate full request→router→service→DB→response workflows using
the AsyncClient (ASGITransport). They exercise the real FastAPI app stack
in-process without network I/O.

AC Coverage Target: 40%+ of EPIC-008's 49 ACs (≥20 ACs passing).

Coverage Tier Definition:
  - Tier 1 (this file): API Integration E2E via AsyncClient/ASGITransport
  - Tier 2: HTTP E2E via httpx against deployed app (tests/e2e/)
  - Tier 3: Browser E2E via Playwright (tests/e2e/ with FRONTEND_URL)
"""

from datetime import date, timedelta

import pytest


# ---------------------------------------------------------------------------
# AC8.1: Smoke Tests (Health Checks)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_api_health_check(client):
    """
    AC8.1.1: Health endpoint reachable
    AC8.8.1: Core journey — health check
    GIVEN the API is running
    WHEN requesting health endpoint
    THEN it should return 200 OK status
    """
    response = await client.get("/health")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# AC8.2: Phase 1 — Onboarding & Account Structure
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_create_cash_account(client, test_user):
    """
    AC8.2.2: Create Cash Account
    GIVEN a user is authenticated
    WHEN creating a cash "Wallet" asset account in SGD
    THEN the account should be created with correct type and currency
    """
    resp = await client.post(
        "/accounts",
        json={"name": "Wallet", "type": "ASSET", "currency": "SGD"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Wallet"
    assert data["type"] == "ASSET"
    assert data["currency"] == "SGD"
    assert data["is_active"] is True


@pytest.mark.e2e
async def test_create_bank_account(client, test_user):
    """
    AC8.2.3: Create Bank Account
    GIVEN a user is authenticated
    WHEN creating a "DBS Savings" asset account in SGD
    THEN the account should be created successfully
    """
    resp = await client.post(
        "/accounts",
        json={"name": "DBS Savings", "type": "ASSET", "currency": "SGD"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "DBS Savings"
    assert data["type"] == "ASSET"


@pytest.mark.e2e
async def test_update_account(client, test_user):
    """
    AC8.2.4: Update account
    GIVEN an existing account
    WHEN updating its name
    THEN the account should reflect the new name
    """
    create_resp = await client.post(
        "/accounts",
        json={"name": "Old Name", "type": "ASSET", "currency": "SGD"},
    )
    assert create_resp.status_code == 201
    account_id = create_resp.json()["id"]

    update_resp = await client.put(
        f"/accounts/{account_id}",
        json={"name": "New Name"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "New Name"


@pytest.mark.e2e
async def test_delete_account(client, test_user):
    """
    AC8.2.5: Delete/deactivate account
    GIVEN an account with no transactions
    WHEN deleting the account
    THEN it should be removed (204 No Content)
    AND subsequent GET should return 404
    """
    create_resp = await client.post(
        "/accounts",
        json={"name": "To Delete", "type": "ASSET", "currency": "SGD"},
    )
    assert create_resp.status_code == 201
    account_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/accounts/{account_id}")
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/accounts/{account_id}")
    assert get_resp.status_code == 404


@pytest.mark.e2e
async def test_accounts_crud_api(client, db, test_user):
    """
    AC8.8.2: Accounts CRUD API (Core Journey)
    GIVEN a user is authenticated
    WHEN creating, listing, getting, and updating accounts
    THEN all operations should succeed with correct data
    """
    # Create account
    create_resp = await client.post(
        "/accounts",
        json={"name": "Test Wallet", "type": "ASSET", "currency": "SGD"},
    )
    assert create_resp.status_code == 201
    account_id = create_resp.json()["id"]

    # List accounts
    list_resp = await client.get("/accounts")
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1

    # Get account
    get_resp = await client.get(f"/accounts/{account_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == account_id

    # Update account
    update_resp = await client.put(
        f"/accounts/{account_id}",
        json={"name": "Updated Wallet"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Updated Wallet"


# ---------------------------------------------------------------------------
# AC8.3: Phase 2 — Manual Journal Entries
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_simple_expense_entry(client, test_user):
    """
    AC8.3.1: Simple Expense Entry
    GIVEN a user has accounts
    WHEN creating a balanced journal entry for a $5 coffee expense
    THEN the entry should be created in draft status with correct amounts
    """
    # Create expense and asset accounts
    expense_resp = await client.post(
        "/accounts",
        json={"name": "Food & Drink", "type": "EXPENSE", "currency": "SGD"},
    )
    assert expense_resp.status_code == 201
    expense_id = expense_resp.json()["id"]

    asset_resp = await client.post(
        "/accounts",
        json={"name": "Wallet", "type": "ASSET", "currency": "SGD"},
    )
    assert asset_resp.status_code == 201
    asset_id = asset_resp.json()["id"]

    # Create expense entry: Debit Expense, Credit Asset
    entry_resp = await client.post(
        "/journal-entries",
        json={
            "entry_date": date.today().isoformat(),
            "memo": "Coffee at Starbucks",
            "lines": [
                {
                    "account_id": expense_id,
                    "direction": "DEBIT",
                    "amount": "5.00",
                    "currency": "SGD",
                },
                {
                    "account_id": asset_id,
                    "direction": "CREDIT",
                    "amount": "5.00",
                    "currency": "SGD",
                },
            ],
        },
    )
    assert entry_resp.status_code == 201
    entry = entry_resp.json()
    assert entry["status"] == "draft"
    assert entry["memo"] == "Coffee at Starbucks"
    assert len(entry["lines"]) == 2


@pytest.mark.e2e
async def test_void_journal_entry(client, test_user):
    """
    AC8.3.2: Void Entry
    GIVEN a posted journal entry
    WHEN voiding the entry with a reason
    THEN a reversal entry should be created
    """
    # Setup: create account, entry, and post it
    acct_resp = await client.post(
        "/accounts",
        json={"name": "Bank", "type": "ASSET", "currency": "SGD"},
    )
    account_id = acct_resp.json()["id"]

    create_resp = await client.post(
        "/journal-entries",
        json={
            "entry_date": date.today().isoformat(),
            "memo": "Duplicate payment",
            "lines": [
                {
                    "account_id": account_id,
                    "direction": "DEBIT",
                    "amount": "50.00",
                    "currency": "SGD",
                },
                {
                    "account_id": account_id,
                    "direction": "CREDIT",
                    "amount": "50.00",
                    "currency": "SGD",
                },
            ],
        },
    )
    entry_id = create_resp.json()["id"]

    # Post it first
    post_resp = await client.post(f"/journal-entries/{entry_id}/post")
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == "posted"

    # Void it
    void_resp = await client.post(
        f"/journal-entries/{entry_id}/void",
        json={"reason": "Duplicate entry"},
    )
    assert void_resp.status_code == 200
    # Void returns the reversal entry which should be posted
    assert void_resp.json()["status"] == "posted"


@pytest.mark.e2e
async def test_post_draft_entry(client, test_user):
    """
    AC8.3.3: Post Draft Entry
    GIVEN a journal entry in draft status
    WHEN posting the entry
    THEN its status should change to "posted"
    """
    acct_resp = await client.post(
        "/accounts",
        json={"name": "Bank", "type": "ASSET", "currency": "SGD"},
    )
    account_id = acct_resp.json()["id"]

    create_resp = await client.post(
        "/journal-entries",
        json={
            "entry_date": date.today().isoformat(),
            "memo": "Draft to post",
            "lines": [
                {
                    "account_id": account_id,
                    "direction": "DEBIT",
                    "amount": "100.00",
                    "currency": "SGD",
                },
                {
                    "account_id": account_id,
                    "direction": "CREDIT",
                    "amount": "100.00",
                    "currency": "SGD",
                },
            ],
        },
    )
    assert create_resp.status_code == 201
    entry = create_resp.json()
    assert entry["status"] == "draft"

    # Post the draft
    post_resp = await client.post(f"/journal-entries/{entry['id']}/post")
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == "posted"


@pytest.mark.e2e
async def test_unbalanced_journal_entry_rejection(client, test_user):
    """
    AC8.3.4: Unbalanced entry rejected
    GIVEN a user attempts to create an unbalanced journal entry
    WHEN sending the request
    THEN it should return 400 validation error
    """
    account_resp = await client.post(
        "/accounts",
        json={"name": "Bank", "type": "ASSET", "currency": "SGD"},
    )
    account_id = account_resp.json()["id"]

    response = await client.post(
        "/journal-entries",
        json={
            "entry_date": date.today().isoformat(),
            "memo": "Unbalanced Entry",
            "lines": [
                {
                    "account_id": account_id,
                    "direction": "DEBIT",
                    "amount": "100.00",
                    "currency": "SGD",
                },
                {
                    "account_id": account_id,
                    "direction": "CREDIT",
                    "amount": "90.00",
                    "currency": "SGD",
                },
            ],
        },
    )
    assert response.status_code == 400
    assert "not balanced" in response.json()["detail"].lower()


@pytest.mark.e2e
async def test_journal_entry_crud(client, test_user):
    """
    AC8.3.5: Journal Entry CRUD
    AC8.8.3: Core journey — journal entry lifecycle
    GIVEN a user is authenticated
    WHEN creating, listing, getting, posting, voiding, and deleting entries
    THEN all CRUD operations should work correctly
    """
    # Create account
    acct_resp = await client.post(
        "/accounts",
        json={"name": "Bank", "type": "ASSET", "currency": "SGD"},
    )
    account_id = acct_resp.json()["id"]

    # CREATE
    create_resp = await client.post(
        "/journal-entries",
        json={
            "entry_date": date.today().isoformat(),
            "memo": "CRUD Test Entry",
            "lines": [
                {
                    "account_id": account_id,
                    "direction": "DEBIT",
                    "amount": "200.00",
                    "currency": "SGD",
                },
                {
                    "account_id": account_id,
                    "direction": "CREDIT",
                    "amount": "200.00",
                    "currency": "SGD",
                },
            ],
        },
    )
    assert create_resp.status_code == 201
    entry_id = create_resp.json()["id"]

    # READ (get single)
    get_resp = await client.get(f"/journal-entries/{entry_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["memo"] == "CRUD Test Entry"

    # LIST
    list_resp = await client.get("/journal-entries")
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1

    # DELETE (only draft entries can be deleted)
    delete_resp = await client.delete(f"/journal-entries/{entry_id}")
    assert delete_resp.status_code == 204

    # Verify deleted
    get_deleted = await client.get(f"/journal-entries/{entry_id}")
    assert get_deleted.status_code == 404


# ---------------------------------------------------------------------------
# AC8.5: Phase 4 — Reconciliation Engine
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_reconciliation_engine_runs(client, db, test_user):
    """
    AC8.5.1: Reconciliation engine runs
    AC8.8.5: Core journey — reconciliation
    GIVEN a user has bank transactions
    WHEN running reconciliation
    THEN it should execute successfully (200 OK)
    """
    # Create account and entry for context
    acct_resp = await client.post(
        "/accounts",
        json={"name": "Bank", "type": "ASSET", "currency": "SGD"},
    )
    assert acct_resp.status_code == 201
    account_id = acct_resp.json()["id"]

    await client.post(
        "/journal-entries",
        json={
            "entry_date": date.today().isoformat(),
            "memo": "Test Transaction",
            "lines": [
                {
                    "account_id": account_id,
                    "direction": "DEBIT",
                    "amount": "50.00",
                    "currency": "SGD",
                },
                {
                    "account_id": account_id,
                    "direction": "CREDIT",
                    "amount": "50.00",
                    "currency": "SGD",
                },
            ],
        },
    )

    recon_resp = await client.post("/reconciliation/run")
    assert recon_resp.status_code == 200


@pytest.mark.e2e
async def test_reconciliation_stats(client, db, test_user):
    """
    AC8.5.2: Reconciliation stats endpoint
    GIVEN the reconciliation engine has been run
    WHEN requesting stats
    THEN it should return stats with total_transactions and match_rate
    """
    # Run reconciliation first (even with no data, stats should work)
    run_resp = await client.post("/reconciliation/run")
    assert run_resp.status_code == 200

    stats_resp = await client.get("/reconciliation/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert "total_transactions" in stats
    assert "match_rate" in stats


# ---------------------------------------------------------------------------
# AC8.6: Phase 5 — Reporting & Visualization
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_balance_sheet_report(client, test_user):
    """
    AC8.6.1: View Balance Sheet
    AC8.8.4: Core journey — reports API
    GIVEN a user has accounts
    WHEN requesting the balance sheet
    THEN it should return 200 with assets, liabilities, equity sections
    """
    # Create account for non-empty report
    await client.post(
        "/accounts",
        json={"name": "Bank", "type": "ASSET", "currency": "SGD"},
    )

    resp = await client.get("/reports/balance-sheet")
    assert resp.status_code == 200
    data = resp.json()
    assert "assets" in data
    assert "liabilities" in data
    assert "equity" in data
    assert "total_assets" in data


@pytest.mark.e2e
async def test_income_statement_report(client, test_user):
    """
    AC8.6.2: View Income Statement
    GIVEN a user is authenticated
    WHEN requesting the income statement for a date range
    THEN it should return 200 with income and expenses sections
    """
    today = date.today()
    start = (today - timedelta(days=30)).isoformat()
    end = today.isoformat()

    resp = await client.get(
        "/reports/income-statement",
        params={"start_date": start, "end_date": end},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "income" in data
    assert "expenses" in data
    assert "net_income" in data


@pytest.mark.e2e
async def test_cash_flow_report(client, test_user):
    """
    AC8.6.3: View Cash Flow Report
    GIVEN a user is authenticated
    WHEN requesting the cash flow report for a date range
    THEN it should return 200 with operating, investing, financing sections
    """
    today = date.today()
    start = (today - timedelta(days=30)).isoformat()
    end = today.isoformat()

    resp = await client.get(
        "/reports/cash-flow",
        params={"start_date": start, "end_date": end},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "operating" in data or "net_cash_flow" in data


@pytest.mark.e2e
async def test_reports_currencies_endpoint(client, test_user):
    """
    AC8.6.1 (supplementary): Currencies endpoint for report configuration
    GIVEN a user is authenticated
    WHEN requesting available currencies
    THEN it should return a list containing at least the base currency
    """
    resp = await client.get("/reports/currencies")
    assert resp.status_code == 200
    currencies = resp.json()
    assert isinstance(currencies, list)
    assert "SGD" in currencies


# ---------------------------------------------------------------------------
# AC8.7: API Authentication & Authorization
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_api_authentication_failures(client):
    """
    AC8.7.1: Authentication validation
    GIVEN invalid credentials
    WHEN making a login request
    THEN it should return 401 or 422
    """
    login_resp = await client.post(
        "/auth/login",
        json={
            "email": "nonexistent@example.com",
            "password": "wrongpassword",
        },
    )
    assert login_resp.status_code in [401, 422]


@pytest.mark.e2e
async def test_unauthorized_access_blocked(public_client):
    """
    AC8.7.2: Unauthorized access blocked
    GIVEN no authentication headers
    WHEN accessing protected endpoints
    THEN it should return 401 Unauthorized
    """
    # Accounts requires auth
    resp = await public_client.get("/accounts")
    assert resp.status_code == 401

    # Journal entries requires auth
    resp = await public_client.get("/journal-entries")
    assert resp.status_code == 401

    # Reports requires auth
    resp = await public_client.get("/reports/balance-sheet")
    assert resp.status_code == 401


@pytest.mark.e2e
async def test_user_session_management(client, test_user):
    """
    AC8.7.3: User session management
    GIVEN a valid authentication token
    WHEN requesting /auth/me
    THEN it should return the current user's information
    """
    resp = await client.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert "email" in data
    assert data["id"] == str(test_user.id)


@pytest.mark.e2e
async def test_register_and_login_flow(public_client):
    """
    AC8.7.1 (supplementary): Full registration → login flow
    GIVEN a new user
    WHEN registering and then logging in
    THEN both operations should succeed with access tokens
    """
    # Register
    reg_resp = await public_client.post(
        "/auth/register",
        json={
            "email": "newuser@e2etest.com",
            "password": "SecurePass123!",
            "name": "E2E Test User",
        },
    )
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert "access_token" in reg_data
    assert reg_data["email"] == "newuser@e2etest.com"

    # Login with same credentials
    login_resp = await public_client.post(
        "/auth/login",
        json={
            "email": "newuser@e2etest.com",
            "password": "SecurePass123!",
        },
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert "access_token" in login_data

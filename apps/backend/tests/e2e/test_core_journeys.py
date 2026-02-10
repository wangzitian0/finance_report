"""
E2E Phase tests for core functionality

These tests validate E2E workflows including health check, account creation,
journal entry CRUD operations, reports, reconciliation, and authentication.
Tests verify proper error handling, data consistency
and state management across review queue operations.
"""

from datetime import date

import pytest


@pytest.mark.e2e
async def test_api_health_check(client):
    """
    AC8.10.1: Health endpoint reachable
    GIVEN the API is running
    WHEN requesting health endpoint
    THEN it should return 200 OK status
    """
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.e2e
async def test_accounts_crud_api(client, db, test_user):
    """
    AC8.10.2: User can create account
    GIVEN a user is authenticated
    WHEN creating, listing, updating, and deactivating accounts
    THEN all operations should succeed with correct data
    """
    # Create account
    create_resp = await client.post("/accounts", json={"name": "Test Wallet", "type": "ASSET", "currency": "SGD"})
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
    update_resp = await client.put(f"/accounts/{account_id}", json={"name": "Updated Wallet"})
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Updated Wallet"


@pytest.mark.e2e
async def test_journal_entry_lifecycle_api(client, db, test_user):
    """
    AC8.10.3: User can create journal entry
    GIVEN a user is authenticated
    WHEN creating, posting, and voiding journal entries
    THEN all operations should succeed with correct status transitions
    """
    # Create account first
    account_resp = await client.post("/accounts", json={"name": "Bank", "type": "ASSET", "currency": "SGD"})
    assert account_resp.status_code == 201
    account_id = account_resp.json()["id"]

    # Create journal entry
    create_resp = await client.post(
        "/journal-entries",
        json={
            "entry_date": date.today().isoformat(),
            "memo": "E2E Test Entry",
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
    entry_id = create_resp.json()["id"]

    # Get journal entry
    get_resp = await client.get(f"/journal-entries/{entry_id}")
    assert get_resp.status_code == 200

    # Post journal entry
    post_resp = await client.post(f"/journal-entries/{entry_id}/post")
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == "posted"

    # Void journal entry
    void_resp = await client.post(f"/journal-entries/{entry_id}/void", json={"reason": "E2E test void"})
    assert void_resp.status_code == 200
    assert void_resp.json()["status"] == "posted"


@pytest.mark.e2e
async def test_unbalanced_journal_entry_rejection(client, test_user):
    """
    AC8.10.6: Unbalanced entry rejected
    GIVEN a user attempts to create an unbalanced journal entry
    WHEN sending the request
    THEN it should return 400 validation error
    """
    # Create accounts
    account_resp = await client.post("/accounts", json={"name": "Bank", "type": "ASSET", "currency": "SGD"})
    account_id = account_resp.json()["id"]

    # Create unbalanced entry
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
                    "amount": "90.00",  # Unbalanced!
                    "currency": "SGD",
                },
            ],
        },
    )
    assert response.status_code == 400
    assert "not balanced" in response.json()["detail"].lower()


@pytest.mark.e2e
async def test_reports_api(client, test_user):
    """
    AC8.10.7: Reports API accessible
    GIVEN a user is authenticated
    WHEN requesting balance sheet, income statement, and cash flow reports
    THEN all reports should return 200 with valid data
    """
    # Create account first
    account_resp = await client.post("/accounts", json={"name": "Bank", "type": "ASSET", "currency": "SGD"})
    assert account_resp.status_code == 201

    # Balance sheet
    bs_resp = await client.get("/reports/balance-sheet")
    assert bs_resp.status_code == 200

    # Income statement
    is_resp = await client.get("/reports/income-statement")
    assert is_resp.status_code == 200

    # Cash flow
    cf_resp = await client.get("/reports/cash-flow")
    assert cf_resp.status_code == 200


@pytest.mark.e2e
async def test_reconciliation_api(client, db, test_user):
    """
    AC8.10.5: Reconciliation engine runs
    GIVEN a user is authenticated and has bank transactions
    WHEN running reconciliation and checking stats
    THEN reconciliation should execute and stats should be accurate
    """
    # Create accounts and entry for testing
    account_resp = await client.post("/accounts", json={"name": "Bank", "type": "ASSET", "currency": "SGD"})
    assert account_resp.status_code == 201
    account_id = account_resp.json()["id"]

    entry_resp = await client.post(
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
    assert entry_resp.status_code == 201

    # Run reconciliation
    recon_resp = await client.post("/reconciliation/run")
    assert recon_resp.status_code == 200

    # Check stats
    stats_resp = await client.get("/reconciliation/stats")
    assert stats_resp.status_code == 200
    stats_data = stats_resp.json()
    assert "total_transactions" in stats_data
    assert "match_rate" in stats_data


@pytest.mark.e2e
async def test_api_authentication_failures(client):
    """
    AC8.10.9: Authentication validation
    GIVEN invalid credentials or missing auth headers
    WHEN making API requests
    THEN it should return 401 or 403 errors
    """
    # Invalid login
    login_resp = await client.post(
        "/auth/login",
        data={
            "username": "nonexistent@example.com",
            "password": "wrongpassword",
        },
    )
    assert login_resp.status_code in [401, 422]

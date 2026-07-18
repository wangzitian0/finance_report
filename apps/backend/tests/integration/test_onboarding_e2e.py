"""First-run backend journey integration tests."""

from decimal import Decimal
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import verify_accounting_equation


async def test_AC1_9_1_first_run_registration_account_entry_journey(
    public_client: AsyncClient,
    db: AsyncSession,
) -> None:
    """AC-ledger.77.1: AC1.9.1: A new user can register, log in, create accounts, post first entry, and remain balanced."""
    email = "first-run-ledger@example.com"
    password = "CorrectHorseBatteryStaple1!"

    register_response = await public_client.post(
        "/auth/register",
        json={"email": email, "password": password, "name": "First Run User"},
    )
    assert register_response.status_code == 201
    registered = register_response.json()
    assert registered["access_token"]

    login_response = await public_client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert login_response.status_code == 200
    logged_in = login_response.json()
    token = logged_in["access_token"]
    user_id = UUID(logged_in["id"])

    auth_headers = {"Authorization": f"Bearer {token}"}
    cash_response = await public_client.post(
        "/accounts",
        headers=auth_headers,
        json={
            "name": "Cash",
            "code": "1001",
            "type": "ASSET",
            "currency": "SGD",
        },
    )
    salary_response = await public_client.post(
        "/accounts",
        headers=auth_headers,
        json={
            "name": "Salary Income",
            "code": "4001",
            "type": "INCOME",
            "currency": "SGD",
        },
    )
    assert cash_response.status_code == 201
    assert salary_response.status_code == 201
    cash_account = cash_response.json()
    salary_account = salary_response.json()

    entry_response = await public_client.post(
        "/journal-entries",
        headers=auth_headers,
        json={
            "entry_date": "2026-01-31",
            "memo": "First salary deposit",
            "lines": [
                {
                    "account_id": cash_account["id"],
                    "direction": "DEBIT",
                    "amount": "1250.00",
                    "currency": "SGD",
                },
                {
                    "account_id": salary_account["id"],
                    "direction": "CREDIT",
                    "amount": "1250.00",
                    "currency": "SGD",
                },
            ],
        },
    )
    assert entry_response.status_code == 201
    draft_entry = entry_response.json()
    assert draft_entry["status"] == "draft"

    post_response = await public_client.post(
        f"/journal-entries/{draft_entry['id']}/postings",
        headers=auth_headers,
    )
    assert post_response.status_code == 200
    posted_entry = post_response.json()
    assert posted_entry["status"] == "posted"

    accounts_response = await public_client.get(
        "/accounts?include_balance=true",
        headers=auth_headers,
    )
    assert accounts_response.status_code == 200
    account_balances = {item["code"]: Decimal(str(item["balance"])) for item in accounts_response.json()["items"]}
    assert account_balances["1001"] == Decimal("1250.00")
    assert account_balances["4001"] == Decimal("1250.00")
    assert await verify_accounting_equation(db, user_id, base_currency="SGD")

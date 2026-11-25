from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration
from sqlalchemy.ext.asyncio import AsyncSession
from src.ledger import verify_accounting_equation


async def test_first_run_registration_account_entry_journey(public_client: AsyncClient, db: AsyncSession) -> None:
    creds = {"email": "first-run-ledger@example.com", "password": "CorrectHorseBatteryStaple1!"}
    reg = await public_client.post("/auth/register", json={**creds, "name": "First Run User"})
    assert reg.status_code == 201 and reg.json()["access_token"]

    login = await public_client.post("/auth/login", json=creds)
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    cash = await public_client.post(
        "/accounts", headers=headers, json={"name": "Cash", "code": "1001", "type": "ASSET", "currency": "SGD"}
    )
    salary = await public_client.post(
        "/accounts",
        headers=headers,
        json={"name": "Salary Income", "code": "4001", "type": "INCOME", "currency": "SGD"},
    )
    assert (cash.status_code, salary.status_code) == (201, 201)

    entry = await public_client.post(
        "/journal-entries",
        headers=headers,
        json={
            "entry_date": "2026-01-31",
            "memo": "First salary deposit",
            "lines": [
                {"account_id": cash.json()["id"], "direction": "DEBIT", "amount": "1250.00", "currency": "SGD"},
                {"account_id": salary.json()["id"], "direction": "CREDIT", "amount": "1250.00", "currency": "SGD"},
            ],
        },
    )
    assert entry.status_code == 201 and entry.json()["status"] == "draft"
    post = await public_client.post(f"/journal-entries/{entry.json()['id']}/postings", headers=headers)
    accounts = await public_client.get("/accounts?include_balance=true", headers=headers)
    balances = {item["code"]: Decimal(str(item["balance"])) for item in accounts.json()["items"]}
    assert (post.status_code, post.json()["status"], accounts.status_code, balances["1001"], balances["4001"]) == (
        200,
        "posted",
        200,
        Decimal("1250.00"),
        Decimal("1250.00"),
    )
    assert await verify_accounting_equation(db, UUID(login.json()["id"]), base_currency="SGD")

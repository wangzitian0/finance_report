"""AC2.10.1 - AC2.10.1: Accounts API Endpoint Tests

These tests validate accounts API endpoints including CRUD operations,
filtering, status checks, and balance queries.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient


async def _create_account(client: AsyncClient, name: str, account_type: str) -> dict:
    payload = {"name": name, "type": account_type, "currency": "SGD"}
    resp = await client.post("/accounts", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_accounts_endpoints(client: AsyncClient) -> None:
    account = await _create_account(client, "Cash", "ASSET")

    basic_list_resp = await client.get("/accounts")
    assert basic_list_resp.status_code == 200
    assert basic_list_resp.json()["total"] >= 1

    list_resp = await client.get("/accounts", params={"include_balance": "true"})
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    assert list_data["items"][0]["balance"] is not None

    filter_resp = await client.get("/accounts", params={"account_type": "ASSET"})
    assert filter_resp.status_code == 200

    get_resp = await client.get(f"/accounts/{account['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == account["id"]

    update_resp = await client.put(
        f"/accounts/{account['id']}",
        json={"name": "Cash Vault", "code": "1001", "description": "Updated"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Cash Vault"

    deactivate_resp = await client.put(
        f"/accounts/{account['id']}",
        json={"is_active": False},
    )
    assert deactivate_resp.status_code == 200
    assert deactivate_resp.json()["is_active"] is False

    inactive_resp = await client.get("/accounts", params={"is_active": "false"})
    assert inactive_resp.status_code == 200
    assert inactive_resp.json()["total"] >= 1

    missing_resp = await client.get(f"/accounts/{uuid4()}")
    assert missing_resp.status_code == 404

    missing_update = await client.put(
        f"/accounts/{uuid4()}",
        json={"name": "Missing"},
    )
    assert missing_update.status_code == 404

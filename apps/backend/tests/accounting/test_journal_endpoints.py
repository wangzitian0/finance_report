"""AC2.10.1 - AC2.10.1: Journal Entry API Endpoint Tests

These tests validate journal entry API endpoints including CRUD operations,
filtering, status checks, posting, and voiding.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient


async def _create_account(client: AsyncClient, name: str, account_type: str) -> dict:
    payload = {"name": name, "type": account_type, "currency": "SGD"}
    resp = await client.post("/accounts", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_journal_entry_endpoints(client: AsyncClient) -> None:
    """AC2.10.1: Journal entry API endpoints
    GIVEN authenticated user
    WHEN interacting with journal entry API
    THEN all CRUD operations and status transitions should work correctly
    """
    debit_account = await _create_account(client, "Bank", "ASSET")
    credit_account = await _create_account(client, "Revenue", "INCOME")

    entry_payload = {
        "entry_date": date.today().isoformat(),
        "memo": "Test entry",
        "lines": [
            {
                "account_id": debit_account["id"],
                "direction": "DEBIT",
                "amount": "100.00",
                "currency": "SGD",
            },
            {
                "account_id": credit_account["id"],
                "direction": "CREDIT",
                "amount": "100.00",
                "currency": "SGD",
            },
        ],
    }
    create_resp = await client.post("/journal-entries", json=entry_payload)
    assert create_resp.status_code == 201
    entry = create_resp.json()

    older_date = date.today() - timedelta(days=10)
    older_payload = {
        "entry_date": older_date.isoformat(),
        "memo": "Older entry",
        "lines": [
            {
                "account_id": debit_account["id"],
                "direction": "DEBIT",
                "amount": "50.00",
                "currency": "SGD",
            },
            {
                "account_id": credit_account["id"],
                "direction": "CREDIT",
                "amount": "50.00",
                "currency": "SGD",
            },
        ],
    }
    older_resp = await client.post("/journal-entries", json=older_payload)
    assert older_resp.status_code == 201
    older_entry = older_resp.json()

    list_resp = await client.get("/journal-entries", params={"status_filter": "draft"})
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1

    start_date_resp = await client.get(
        "/journal-entries",
        params={"start_date": date.today().isoformat()},
    )
    assert start_date_resp.status_code == 200
    start_ids = {item["id"] for item in start_date_resp.json()["items"]}
    assert older_entry["id"] not in start_ids

    end_date_resp = await client.get(
        "/journal-entries",
        params={"end_date": older_date.isoformat()},
    )
    assert end_date_resp.status_code == 200
    end_ids = {item["id"] for item in end_date_resp.json()["items"]}
    assert older_entry["id"] in end_ids

    get_resp = await client.get(f"/journal-entries/{entry['id']}")
    assert get_resp.status_code == 200

    missing_get = await client.get(f"/journal-entries/{uuid4()}")
    assert missing_get.status_code == 404

    post_resp = await client.post(f"/journal-entries/{entry['id']}/post")
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == "posted"

    void_resp = await client.post(
        f"/journal-entries/{entry['id']}/void",
        json={"reason": "Test void"},
    )
    assert void_resp.status_code == 200
    assert void_resp.json()["status"] == "posted"

    missing_post = await client.post(f"/journal-entries/{uuid4()}/post")
    assert missing_post.status_code == 400

    missing_void = await client.post(
        f"/journal-entries/{uuid4()}/void",
        json={"reason": "missing"},
    )
    assert missing_void.status_code == 400

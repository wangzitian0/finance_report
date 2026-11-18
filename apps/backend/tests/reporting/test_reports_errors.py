from datetime import date
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity import create_access_token
from tests.ledger._ledger_helpers import create_valid_posted_entry


@pytest.mark.parametrize(
    ("payload", "detail_substr"),
    [({"not_sub": "val"}, "missing subject"), ({"sub": "not-a-uuid"}, "invalid user id format")],
)
async def test_auth_coverage_errors(client: AsyncClient, payload: dict, detail_substr: str) -> None:
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {create_access_token(data=payload)}"})
    assert resp.status_code == 401 and detail_substr in resp.json()["detail"].lower()


async def test_journal_accounts_reconciliation_coverage_errors(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    for method, path, extra, code in (
        ("get", f"/journal-entries/{uuid4()}", {}, 404),
        ("post", f"/journal-entries/{uuid4()}/postings", {}, 404),
        ("post", f"/journal-entries/{uuid4()}/voidings", {"json": {"reason": "test"}}, 400),
        ("delete", f"/journal-entries/{uuid4()}", {}, 404),
        ("put", f"/accounts/{uuid4()}", {"json": {"name": "New"}}, 404),
        ("delete", f"/accounts/{uuid4()}", {}, 404),
    ):
        assert (await getattr(client, method)(path, **extra)).status_code == code
    entry = await create_valid_posted_entry(db, test_user.id, entry_date=date.today(), memo="Posted")
    del_resp = await client.delete(f"/journal-entries/{entry.id}")
    assert del_resp.status_code == 400 and "draft" in del_resp.json()["detail"].lower()

    for action in ("accept", "reject"):
        resp = await client.patch(f"/reconciliation/matches/{uuid4()}", json={"action": action})
        assert resp.status_code == 404
    batch = await client.post("/reconciliation/matches", json={"action": "accept", "match_ids": []})
    assert batch.status_code == 200 and batch.json()["approved_count"] == 0

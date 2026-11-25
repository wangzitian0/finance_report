"""Tenant ownership and self-parent checks for account parent references (#2957)."""

from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity import User, create_access_token
from src.ledger import Account


def _auth_headers(user_id: object) -> dict[str, str]:
    token = create_access_token(data={"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


async def _create_other_user(db: AsyncSession) -> User:
    other = User(id=uuid4(), email=f"other-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other)
    await db.commit()
    return other


async def test_cross_tenant_parent_rejected_on_create_and_update_and_allows_owner_delete(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Reject cross-tenant parent_id on create and update with 404, leaving owner delete unblocked."""
    user_b = await _create_other_user(db)
    headers_b = _auth_headers(user_b.id)

    resp_a = await client.post("/accounts", json={"name": "Parent A", "type": "ASSET", "currency": "SGD"})
    assert resp_a.status_code == 201
    parent_a_id = resp_a.json()["id"]

    # Random missing parent_id must match cross-tenant status (404).
    resp_missing = await client.post(
        "/accounts",
        json={"name": "Missing Parent", "type": "ASSET", "currency": "SGD", "parent_id": str(uuid4())},
        headers=headers_b,
    )
    assert resp_missing.status_code == 404

    resp_cross_create = await client.post(
        "/accounts",
        json={"name": "Child B", "type": "ASSET", "currency": "SGD", "parent_id": parent_a_id},
        headers=headers_b,
    )
    assert resp_cross_create.status_code == 404

    count_b = (
        await db.execute(select(func.count()).select_from(Account).where(Account.user_id == user_b.id))
    ).scalar_one()
    assert count_b == 0

    resp_b_own = await client.post(
        "/accounts",
        json={"name": "Own B", "type": "ASSET", "currency": "SGD"},
        headers=headers_b,
    )
    assert resp_b_own.status_code == 201
    own_b_id = resp_b_own.json()["id"]

    resp_cross_update = await client.put(
        f"/accounts/{own_b_id}",
        json={"parent_id": parent_a_id},
        headers=headers_b,
    )
    assert resp_cross_update.status_code == 404

    db.expire_all()
    refreshed_b = (await db.execute(select(Account).where(Account.id == own_b_id))).scalar_one()
    assert refreshed_b.parent_id is None

    # Owner A deletes Parent A without IntegrityError from cross-tenant references.
    resp_del_a = await client.delete(f"/accounts/{parent_a_id}")
    assert resp_del_a.status_code == 204


async def test_own_parent_create_update_succeeds_and_self_parent_rejected(client: AsyncClient) -> None:
    """Allow owned parent_id on create and update, and reject self-parenting on update."""
    parent_a = (await client.post("/accounts", json={"name": "Parent 1", "type": "ASSET", "currency": "SGD"})).json()
    parent_b = (await client.post("/accounts", json={"name": "Parent 2", "type": "ASSET", "currency": "SGD"})).json()

    child_resp = await client.post(
        "/accounts",
        json={"name": "Child", "type": "ASSET", "currency": "SGD", "parent_id": parent_a["id"]},
    )
    assert child_resp.status_code == 201
    child_id = child_resp.json()["id"]
    assert child_resp.json()["parent_id"] == parent_a["id"]

    update_resp = await client.put(f"/accounts/{child_id}", json={"parent_id": parent_b["id"]})
    assert update_resp.status_code == 200
    assert update_resp.json()["parent_id"] == parent_b["id"]

    self_resp = await client.put(f"/accounts/{child_id}", json={"parent_id": child_id})
    assert self_resp.status_code == 400

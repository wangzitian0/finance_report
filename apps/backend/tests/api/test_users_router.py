"""API tests for user management endpoints."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity import User, create_access_token
from src.models.statement_enums import BankStatementStatus
from tests.factories import StatementSummaryFactory

pytestmark = pytest.mark.asyncio


async def test_delete_current_user_removes_authenticated_user(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC8.13.109: isolated E2E users can be cleaned up after provider gates."""
    response = await client.delete(f"/users/{test_user.id}")

    assert response.status_code == 204
    assert await db.scalar(select(User.id).where(User.id == test_user.id)) is None

    followup = await client.get("/users")
    assert followup.status_code == 401


async def test_delete_user_does_not_allow_cross_user_deletion(
    public_client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC8.13.109: cleanup endpoint remains scoped to the authenticated user."""
    other_user = User(email=f"other-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other_user)
    await db.commit()
    await db.refresh(other_user)

    token = create_access_token(data={"sub": str(test_user.id)})
    response = await public_client.delete(
        f"/users/{other_user.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert await db.scalar(select(User.id).where(User.id == other_user.id)) == other_user.id


async def test_delete_user_with_immutable_entries_returns_409(
    client: AsyncClient,
    test_user: User,
) -> None:
    """AC-ledger.14.6: when the cascade is blocked by the ledger immutability invariant
    (posted/reconciled entries), account deletion returns a clean 409, not a leaked 500.

    The invariant is a DB trigger present only on the migrated database, not the
    metadata-built test schema, so we inject the IntegrityError it raises and assert the
    endpoint surfaces it as a 409 (see #988: the same condition leaks a 500 on staging).
    """
    immutable_violation = IntegrityError(
        "DELETE FROM users WHERE users.id = $1::UUID",
        {},
        Exception("cannot delete immutable journal entry ... with status reconciled"),
    )
    with patch.object(AsyncSession, "commit", new_callable=AsyncMock, side_effect=immutable_violation):
        response = await client.delete(f"/users/{test_user.id}")

    assert response.status_code == 409


async def test_AC13_23_1_delete_user_with_in_flight_parse_returns_409(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC-extraction.123.1 (#1256): deleting a user while a statement parse is still
    in-flight (``status == PARSING``) is refused with HTTP 409 and an actionable
    message, instead of cascading the delete out from under the running parse.

    Without this guard, the cascade removes the user/statement rows and the
    background parse then writes ``uploaded_documents.user_id`` for the now-gone
    user, hitting a FK IntegrityError (and masking the original error).
    """
    await StatementSummaryFactory.create_async(db, user_id=test_user.id, status=BankStatementStatus.PARSING)
    await db.commit()

    response = await client.delete(f"/users/{test_user.id}")

    assert response.status_code == 409
    assert "pars" in response.json()["detail"].lower()
    # The user is not deleted while the parse is in flight.
    assert await db.scalar(select(User.id).where(User.id == test_user.id)) == test_user.id


async def test_AC13_23_1_delete_user_without_in_flight_parse_succeeds(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC-extraction.123.1 (#1256): the in-flight guard is narrow — a user whose statements
    are all in terminal states (no ``PARSING``) deletes normally (204)."""
    await StatementSummaryFactory.create_async(db, user_id=test_user.id, status=BankStatementStatus.PARSED)
    await db.commit()

    response = await client.delete(f"/users/{test_user.id}")

    assert response.status_code == 204
    assert await db.scalar(select(User.id).where(User.id == test_user.id)) is None

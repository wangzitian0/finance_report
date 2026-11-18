from __future__ import annotations

from uuid import uuid4

import pytest
import structlog
from httpx import AsyncClient
from src.identity import create_access_token, get_current_user_id
from src.platform import UnauthorizedError

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    ("auth_header", "expected_detail"),
    [
        (None, "Not authenticated"),
        ("Bearer invalid-token", "Could not validate credentials"),
        ("random_user", "User not found"),
    ],
)
async def test_auth_rejects_unauthenticated_requests(
    public_client: AsyncClient, auth_header: str | None, expected_detail: str
):
    headers = {}
    if auth_header == "random_user":
        headers["Authorization"] = f"Bearer {create_access_token(data={'sub': str(uuid4())})}"
    elif auth_header is not None:
        headers["Authorization"] = auth_header
    response = await public_client.get("/accounts", headers=headers)
    assert response.status_code == 401 and response.json()["detail"] == expected_detail


async def test_auth_valid_user(client: AsyncClient, test_user):
    assert (await client.get("/accounts")).status_code == 200


async def test_get_current_user_id_valid_binds_context_and_rejects_missing(db, test_user):
    structlog.contextvars.clear_contextvars()
    token = create_access_token(data={"sub": str(test_user.id)})
    assert await get_current_user_id(token=token, db=db) == test_user.id
    assert structlog.contextvars.get_contextvars()["user_id"] == str(test_user.id)

    missing_token = create_access_token(data={"sub": str(uuid4())})
    with pytest.raises(UnauthorizedError, match="User not found"):
        await get_current_user_id(token=missing_token, db=db)

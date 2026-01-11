"""Authentication helpers for request-scoped user context."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models import User


async def get_current_user_id(
    x_user_id: UUID | None = Header(default=None, alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
) -> UUID:
    """Resolve the current user ID from request headers.

    This is a temporary auth bridge until full auth is wired in.
    """
    if x_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-User-Id header",
        )

    result = await db.execute(select(User.id).where(User.id == x_user_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user",
        )

    return x_user_id

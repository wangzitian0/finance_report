"""Common FastAPI dependencies for consistent type annotations.

This module provides type aliases for frequently used FastAPI dependencies,
reducing boilerplate and ensuring consistency across routers.

Usage:
    from src.deps import CurrentUserId, DbSession

    async def my_endpoint(db: DbSession, user_id: CurrentUserId):
        # db is AsyncSession with get_db dependency injected
        # user_id is UUID with get_current_user_id dependency injected
        ...
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.database import get_db

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUserId = Annotated[UUID, Depends(get_current_user_id)]

__all__ = ["CurrentUserId", "DbSession"]

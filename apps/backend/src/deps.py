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

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.database import get_db

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUserId = Annotated[UUID, Depends(get_current_user_id)]

# Pagination convention for list endpoints (#1099 AC12.29.2/.3).
# A single default + hard maximum shared by every list endpoint via the
# ``Pagination`` dependency below: the bound (``1 <= limit <= MAX_PAGE_LIMIT``,
# ``offset >= 0``) is enforced here once so the generated frontend client can reuse
# one page-params type instead of each endpoint re-declaring ad-hoc
# ``Query(ge=..., le=...)``. An endpoint needing a different default would declare
# its own dependency rather than overriding these.
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 500


class PaginationParams:
    """Shared bounded ``limit``/``offset`` query params for list endpoints.

    Enforces the pagination contract (``1 <= limit <= MAX_PAGE_LIMIT``,
    ``offset >= 0``) in one place.
    """

    def __init__(
        self,
        limit: Annotated[
            int, Query(ge=1, le=MAX_PAGE_LIMIT, description="Maximum items to return")
        ] = DEFAULT_PAGE_LIMIT,
        offset: Annotated[int, Query(ge=0, description="Number of items to skip")] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


Pagination = Annotated[PaginationParams, Depends()]

__all__ = [
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "CurrentUserId",
    "DbSession",
    "Pagination",
    "PaginationParams",
]

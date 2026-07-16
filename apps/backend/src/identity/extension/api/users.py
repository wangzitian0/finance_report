"""User management API router (the identity transport edge).

Authenticated current-user compatibility routes for the legacy ``/users`` surface
(public registration is owned by ``/auth/register``). Moved verbatim (imports
repointed) from the pre-migration ``src/routers/users.py`` into the package's
single home. The ``User`` aggregate is imported from the identity package's own
SQL adapter; the user-CRUD wire vocabulary lives in ``identity.base`` and the
in-flight-parse guard reads a registered port (see below) —
never ``extraction``'s ``StatementSummary`` ORM directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import CurrentUserId, DbSession
from src.identity.base.types.user import UserCreate, UserResponse, UserUpdate
from src.identity.extension.sql import User
from src.platform import raise_bad_request, raise_conflict, raise_not_found
from src.schemas.user import UserListResponse

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    # Called as (db, user_id) — see the delete_user call site below.
    InFlightParseChecker = Callable[[AsyncSession, UUID], Awaitable["UUID | None"]]

router = APIRouter(prefix="/users", tags=["users"])

# ``extraction`` (L3 domain) owns ``StatementSummary``; identity is also L3
# domain and extraction already ``depends_on`` identity, so a direct import
# here would close a dependency cycle (same inversion as
# ``ledger.register_statement_coverage_reader`` / #1675 D6). main.py wires the
# real ``src.extraction.find_in_flight_parse_id`` at startup; tests register
# a fake/the real function directly.
_in_flight_parse_checker: InFlightParseChecker | None = None


def register_in_flight_parse_checker(checker: InFlightParseChecker) -> None:
    """Wire the in-flight-statement-parse check (see module note above)."""
    global _in_flight_parse_checker
    _in_flight_parse_checker = checker


def _require_in_flight_parse_checker() -> InFlightParseChecker:
    if _in_flight_parse_checker is None:
        raise RuntimeError(
            "users.register_in_flight_parse_checker() was never called — "
            "main.py wires it at startup (#1675 D6); a test exercising this path must call it too."
        )
    return _in_flight_parse_checker


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    *,
    user_id: CurrentUserId,
) -> UserResponse:
    """Deprecated user creation route.

    Public registration is owned by /auth/register so this legacy route cannot
    be used to create arbitrary users.
    """
    _ = (user_data, user_id)
    raise_bad_request("Use /auth/register to create users")


@router.get("", response_model=UserListResponse)
async def list_users(
    limit: int = Query(50, ge=1, le=100, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> UserListResponse:
    """List the authenticated user's profile only."""
    scoped_query = select(User).where(User.id == user_id)
    count_result = await db.execute(select(func.count()).select_from(scoped_query.subquery()))
    total = count_result.scalar_one()

    result = await db.execute(scoped_query.order_by(User.created_at.desc()).limit(limit).offset(offset))
    users = result.scalars().all()

    return UserListResponse(
        items=[UserResponse.model_validate(user) for user in users],
        total=total,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    *,
    db: DbSession,
    current_user_id: CurrentUserId,
) -> UserResponse:
    """Get current user by ID without cross-user disclosure."""
    if user_id != current_user_id:
        raise_not_found("User")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise_not_found("User")

    return UserResponse.model_validate(user)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_data: UserUpdate,
    *,
    db: DbSession,
    current_user_id: CurrentUserId,
) -> UserResponse:
    """Update current user details without cross-user mutation."""
    if user_id != current_user_id:
        raise_not_found("User")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise_not_found("User")

    if user_data.email is not None:
        result = await db.execute(select(User).where(User.email == user_data.email).where(User.id != user_id))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise_bad_request("Invalid update data")
        user.email = user_data.email

    await db.commit()
    await db.refresh(user)

    return UserResponse.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    *,
    db: DbSession,
    current_user_id: CurrentUserId,
) -> None:
    """Delete the authenticated user's own account."""
    if user_id != current_user_id:
        raise_not_found("User")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise_not_found("User")

    # Lifecycle coordination (#1256, AC13.23.1): the user-owned cascade
    # (UserOwnedMixin FK, ON DELETE CASCADE) would remove statement rows out from
    # under a still-running background parse. That parse captured user_id/statement_id
    # and would later write uploaded-document lineage for the now-deleted user,
    # which PostgreSQL rejects with a FK IntegrityError (and the original error gets
    # masked). The in-flight parse is queryable as StatementSummary.status == PARSING,
    # so refuse the delete with an actionable 409 rather than racing the parse
    # (read through the registered port — see module note above).
    in_flight_parse = await _require_in_flight_parse_checker()(db, user_id)
    if in_flight_parse is not None:
        raise_conflict(
            "Cannot delete this user account while a statement is still being parsed. "
            "Wait for the parse to finish (or fail) and try again."
        )

    await db.delete(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        # The ledger immutability invariant (posted/reconciled journal entries cannot be
        # deleted) blocks the cascade. Surface it as a clear 409 instead of leaking a 500.
        await db.rollback()
        raise_conflict(
            "Cannot delete this user account while it has posted or reconciled ledger entries. Void those entries first.",
            cause=exc,
        )

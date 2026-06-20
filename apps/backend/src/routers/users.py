"""User management API router."""

from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src.deps import CurrentUserId, DbSession
from src.models import User
from src.models.statement_enums import BankStatementStatus
from src.models.statement_summary import StatementSummary
from src.schemas import UserCreate, UserListResponse, UserResponse, UserUpdate
from src.utils import raise_bad_request, raise_conflict, raise_not_found

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    user_id: CurrentUserId = None,
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
    db: DbSession = None,
    user_id: CurrentUserId = None,
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
    db: DbSession = None,
    current_user_id: CurrentUserId = None,
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
    db: DbSession = None,
    current_user_id: CurrentUserId = None,
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
    db: DbSession = None,
    current_user_id: CurrentUserId = None,
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
    # so refuse the delete with an actionable 409 rather than racing the parse.
    in_flight_parse = await db.scalar(
        select(StatementSummary.id)
        .where(StatementSummary.user_id == user_id)
        .where(StatementSummary.status == BankStatementStatus.PARSING)
        .limit(1)
    )
    if in_flight_parse is not None:
        raise_conflict(
            "Cannot delete this account while a statement is still being parsed. "
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
            "Cannot delete this account while it has posted or reconciled ledger entries. Void those entries first.",
            cause=exc,
        )

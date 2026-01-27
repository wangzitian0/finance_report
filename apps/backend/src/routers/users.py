"""User management API router."""

from uuid import UUID

import bcrypt
from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from src.deps import DbSession
from src.models import User
from src.schemas import UserCreate, UserListResponse, UserResponse, UserUpdate
from src.utils import raise_bad_request, raise_not_found

router = APIRouter(prefix="/users", tags=["users"])

MOCK_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def hash_password(password: str) -> str:
    """Hash a password."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def get_current_user_id() -> UUID:
    """Return mock user ID until authentication is implemented."""
    return MOCK_USER_ID


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    db: DbSession = None,
) -> UserResponse:
    """Create a new user."""
    result = await db.execute(select(User).where(User.email == user_data.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise_bad_request("Invalid registration data")

    user = User(
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return UserResponse.model_validate(user)


@router.get("", response_model=UserListResponse)
async def list_users(
    limit: int = Query(50, ge=1, le=100, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    db: DbSession = None,
) -> UserListResponse:
    """List all users with pagination."""
    count_result = await db.execute(select(func.count(User.id)))
    total = count_result.scalar_one()

    result = await db.execute(select(User).order_by(User.created_at.desc()).limit(limit).offset(offset))
    users = result.scalars().all()

    return UserListResponse(
        items=[UserResponse.model_validate(user) for user in users],
        total=total,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    db: DbSession = None,
) -> UserResponse:
    """Get user by ID."""
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
) -> UserResponse:
    """Update user details."""
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

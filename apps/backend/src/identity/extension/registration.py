"""User registration domain service."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity.base.types import normalize_email
from src.identity.extension.security import hash_password
from src.identity.extension.sql import SqlUserRepository, User
from src.platform.base.errors import ValidationFailedError


async def register_user(
    db: AsyncSession,
    *,
    email: str,
    name: str | None,
    password: str,
    password_hasher: Callable[[str], str] = hash_password,
) -> User:
    """Create a user row within a savepoint so duplicate emails never poison the session."""
    repo = SqlUserRepository(db)
    normalized_email = normalize_email(email)
    if await repo.get_by_normalized_email(normalized_email):
        raise ValidationFailedError("Email already registered")

    user = User(
        email=normalized_email,
        name=name,
        hashed_password=password_hasher(password),
    )
    try:
        async with db.begin_nested():
            await repo.add(user)
            await db.flush()
    except IntegrityError as exc:
        raise ValidationFailedError("Email already registered") from exc
    await db.refresh(user)
    return user

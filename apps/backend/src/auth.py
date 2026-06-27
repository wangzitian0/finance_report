"""Authentication helpers for request-scoped user context."""

from typing import cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.logger import get_logger
from src.models.user import User
from src.observability import log_security_warning
from src.observability_events import bind_authenticated_user_context
from src.security import decode_access_token

AUTH_COOKIE_NAME = "finance_access_token"
logger = get_logger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def get_current_user_id(
    request: Request = cast(Request, None),
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> UUID:
    """Resolve the current user ID from JWT token."""
    resolved_token = token or (request.cookies.get(AUTH_COOKIE_NAME) if request else None)
    if not resolved_token:
        log_security_warning(logger, "auth.failure", reason="missing_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(resolved_token)
    if not payload:
        log_security_warning(logger, "auth.failure", reason="invalid_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        log_security_warning(logger, "auth.failure", reason="missing_subject")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = UUID(user_id_str)
    except ValueError:
        log_security_warning(logger, "auth.failure", reason="invalid_subject")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID format in token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Performance optimization: verify user existence (optional, but safer)
    result = await db.execute(select(User.id).where(User.id == user_uuid))
    if result.scalar_one_or_none() is None:
        log_security_warning(logger, "auth.failure", reason="user_not_found", user_id=user_uuid)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    bind_authenticated_user_context(user_uuid)
    return user_uuid

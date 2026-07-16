"""Authentication API router (the identity transport edge).

The ``/auth`` router and its domain operations ``register``/``login``/``get_me``.
This is the identity package's HTTP boundary (``extension/api/``); the route
handlers ARE the domain services (registration/login), composing the value
objects, the security domain services, the auth rate limiters, and the
``UserRepository`` SQL adapter. Moved verbatim (imports repointed) from the
pre-migration ``src/routers/auth.py`` into the package's single home.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import src.config
from src.deps import CurrentUserId, DbSession
from src.identity.base.types import (
    AUTH_COOKIE_NAME,
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    normalize_email,
)
from src.identity.extension.auth import oauth2_scheme
from src.identity.extension.observability import bind_authenticated_user_context
from src.identity.extension.rate_limit import auth_rate_limiter, register_rate_limiter
from src.identity.extension.security import create_access_token, hash_password, verify_password
from src.identity.extension.sql import SqlUserRepository, User
from src.observability import get_logger, log_security_warning, record_rate_limit_rejected
from src.platform import RateLimiter, raise_bad_request, raise_not_found, raise_too_many_requests, raise_unauthorized

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)

# SECURITY: Only trust X-Forwarded-For from known proxies
# Set TRUST_PROXY=true when behind a trusted reverse proxy (nginx, cloudflare, etc.)
TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() in ("true", "1", "yes")
COOKIE_SAFE_DEVELOPMENT_ENVS = {"development", "test", "ci"}


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, considering proxies.

    NOTE: X-Forwarded-For is only trusted when TRUST_PROXY=true to prevent
    IP spoofing attacks that could bypass rate limiting.
    """
    if TRUST_PROXY:
        # Check X-Forwarded-For header (set by reverse proxy)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Take the first IP (original client)
            return forwarded.split(",")[0].strip()
    # Fall back to direct connection
    return request.client.host if request.client else "unknown"


def _check_rate_limit(request: Request, limiter: RateLimiter, error_msg: str) -> None:
    """Check rate limit and raise HTTPException if exceeded."""
    client_ip = _get_client_ip(request)
    allowed, retry_after = limiter.is_allowed(client_ip)
    if not allowed:
        record_rate_limit_rejected(scope="auth_route")
        log_security_warning(
            logger,
            "rate_limit.rejected",
            reason="auth_route_rate_limit",
            client_ip=client_ip,
            path=request.url.path,
            retry_after=retry_after,
        )
        raise_too_many_requests(error_msg, retry_after=retry_after)


def _set_auth_cookie(response: Response, access_token: str) -> None:
    """Set the HttpOnly access token cookie used by browser clients."""
    settings = src.config.settings
    environment = str(settings.environment).strip().lower()
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=access_token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=environment not in COOKIE_SAFE_DEVELOPMENT_ENVS,
        samesite="lax",
        path="/",
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    response: Response,
    data: RegisterRequest,
    db: DbSession,
) -> AuthResponse:
    """Register a new user with email and password."""
    # SECURITY: Rate limit registration to prevent abuse
    _check_rate_limit(
        request,
        register_rate_limiter,
        "Too many registration attempts. Please try again later.",
    )

    repo = SqlUserRepository(db)

    # Check if email already exists
    normalized_email = normalize_email(str(data.email))
    existing = await repo.get_by_normalized_email(normalized_email)

    if existing:
        raise_bad_request("Email already registered")

    user = User(
        email=normalized_email,
        name=data.name,
        hashed_password=hash_password(data.password),
    )
    await repo.add(user)
    try:
        await db.commit()
    except IntegrityError as e:
        # Handle race condition: another request created user with same email
        await db.rollback()
        raise_bad_request("Email already registered", cause=e)
    await db.refresh(user)

    # Reset registration rate limit on success
    register_rate_limiter.reset(_get_client_ip(request))

    access_token = create_access_token(data={"sub": str(user.id)})
    _set_auth_cookie(response, access_token)

    return AuthResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        created_at=user.created_at,
        access_token=access_token,
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    request: Request,
    response: Response,
    data: LoginRequest,
    db: DbSession,
) -> AuthResponse:
    """Login with email and password."""
    # SECURITY: Rate limit login attempts to prevent brute-force attacks
    _check_rate_limit(
        request,
        auth_rate_limiter,
        "Too many login attempts. Please try again later.",
    )

    normalized_email = normalize_email(str(data.email))
    user = await SqlUserRepository(db).get_by_normalized_email(normalized_email)

    if not user or not verify_password(data.password, user.hashed_password):
        log_security_warning(
            logger,
            "auth.failure",
            reason="invalid_login",
            client_ip=_get_client_ip(request),
        )
        raise_unauthorized("Invalid email or password")

    bind_authenticated_user_context(user.id)
    logger.info(
        "Successful login",
        user_id=str(user.id),
        client_ip=_get_client_ip(request),
    )

    # Reset rate limit on successful login
    auth_rate_limiter.reset(_get_client_ip(request))

    access_token = create_access_token(data={"sub": str(user.id)})
    _set_auth_cookie(response, access_token)

    return AuthResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        created_at=user.created_at,
        access_token=access_token,
    )


@router.get("/me", response_model=AuthResponse)
async def get_me(
    token: str | None = Depends(oauth2_scheme),
    *,
    user_id: CurrentUserId,
    db: DbSession,
) -> AuthResponse:
    """Get current authenticated user."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise_not_found("User")

    return AuthResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        created_at=user.created_at,
        access_token=token or "",
    )

"""Authentication API router."""

import os

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.auth import oauth2_scheme
from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.models import User
from src.rate_limit import RateLimiter, auth_rate_limiter, register_rate_limiter
from src.schemas.auth import AuthResponse, LoginRequest, RegisterRequest
from src.security import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)

# SECURITY: Only trust X-Forwarded-For from known proxies
# Set TRUST_PROXY=true when behind a trusted reverse proxy (nginx, cloudflare, etc.)
TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() in ("true", "1", "yes")


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
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_msg,
            headers={"Retry-After": str(retry_after)},
        )


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
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

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == data.email))
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        email=data.email,
        name=data.name,
        hashed_password=hash_password(data.password),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # Handle race condition: another request created user with same email
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    await db.refresh(user)

    # Reset registration rate limit on success
    register_rate_limiter.reset(_get_client_ip(request))

    access_token = create_access_token(data={"sub": str(user.id)})

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

    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.hashed_password):
        logger.warning(
            "Failed login attempt",
            client_ip=_get_client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    logger.info(
        "Successful login",
        user_id=str(user.id),
        client_ip=_get_client_ip(request),
    )

    # Reset rate limit on successful login
    auth_rate_limiter.reset(_get_client_ip(request))

    access_token = create_access_token(data={"sub": str(user.id)})

    return AuthResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        created_at=user.created_at,
        access_token=access_token,
    )


@router.get("/me", response_model=AuthResponse)
async def get_me(
    token: str = Depends(oauth2_scheme),
    user_id: CurrentUserId = None,
    db: DbSession = None,
) -> AuthResponse:
    """Get current authenticated user."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return AuthResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        created_at=user.created_at,
        access_token=token,
    )

"""API layer dependencies for FastAPI."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# For future use with token-based auth
security = HTTPBearer()


async def get_user_from_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Get user from token (future implementation)."""
    # TODO: Implement token validation
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Token authentication not yet implemented",
    )

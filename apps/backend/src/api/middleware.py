"""API middleware for FastAPI application."""

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware

from ..core.config import settings


def add_cors_middleware(app):
    """Add CORS middleware to the app."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["Content-Type", "Authorization", "X-User-Id"],
    )


async def logging_middleware(request: Request, call_next):
    """Log requests and responses."""
    # TODO: Implement structured logging
    response = await call_next(request)
    return response

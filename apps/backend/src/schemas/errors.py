"""Structured error contract shared by every router (#1005).

Before this module, every failure was an ``HTTPException(detail="some string")``
and the frontend could only branch on free text. ``ErrorResponse`` gives errors a
machine-readable ``error_id`` so the UI can switch on a code instead of parsing
prose, and declares the 4xx/5xx contract in OpenAPI via ``COMMON_ERROR_RESPONSES``.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ErrorCode(str, Enum):
    """Machine-readable error identifiers surfaced in ``ErrorResponse.error_id``.

    The frontend branches on these values, so they are part of the API contract:
    rename with care. ``http_error`` is the generic fallback for an
    ``HTTPException`` raised without a domain-specific code.
    """

    BAD_REQUEST = "bad_request"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UNPROCESSABLE_ENTITY = "unprocessable_entity"
    CONTENT_TOO_LARGE = "content_too_large"
    TOO_MANY_REQUESTS = "too_many_requests"
    HTTP_ERROR = "http_error"
    INTERNAL_ERROR = "internal_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    GATEWAY_TIMEOUT = "gateway_timeout"


# Map of HTTP status code -> default error_id, used by the HTTPException handler to
# derive a stable code for errors raised the legacy way (``HTTPException(detail=...)``)
# so even un-migrated call sites emit a usable ``error_id``.
STATUS_TO_ERROR_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.CONTENT_TOO_LARGE,
    422: ErrorCode.UNPROCESSABLE_ENTITY,
    429: ErrorCode.TOO_MANY_REQUESTS,
    500: ErrorCode.INTERNAL_ERROR,
    503: ErrorCode.SERVICE_UNAVAILABLE,
    504: ErrorCode.GATEWAY_TIMEOUT,
}


def error_code_for_status(status_code: int) -> ErrorCode:
    """Return the canonical :class:`ErrorCode` for an HTTP status code."""
    if status_code in STATUS_TO_ERROR_CODE:
        return STATUS_TO_ERROR_CODE[status_code]
    return ErrorCode.HTTP_ERROR if status_code < 500 else ErrorCode.INTERNAL_ERROR


class ErrorResponse(BaseModel):
    """Canonical error body returned by every exception handler.

    ``error_id`` is the stable, machine-readable discriminator the frontend
    branches on. ``detail`` stays human-readable for display/logging, and
    ``request_id`` correlates the error with backend logs.
    """

    error_id: str = Field(
        ...,
        description="Machine-readable error code; see ErrorCode.",
        examples=["not_found"],
    )
    detail: str = Field(..., description="Human-readable error message.")
    request_id: str | None = Field(
        default=None,
        description="Correlation id matching the backend structured logs.",
    )


# Reusable OpenAPI ``responses=`` block so the common 4xx/5xx contract is declared
# once and attached to every router (see ``app.include_router(..., responses=...)``).
COMMON_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": ErrorResponse, "description": "Bad request"},
    401: {"model": ErrorResponse, "description": "Unauthorized"},
    404: {"model": ErrorResponse, "description": "Not found"},
    422: {"model": ErrorResponse, "description": "Validation error"},
    500: {"model": ErrorResponse, "description": "Internal server error"},
}

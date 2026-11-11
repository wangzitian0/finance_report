"""Structured error contract shared by every router (#1005)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ErrorCode(str, Enum):
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
    if status_code in STATUS_TO_ERROR_CODE:
        return STATUS_TO_ERROR_CODE[status_code]
    return ErrorCode.HTTP_ERROR if status_code < 500 else ErrorCode.INTERNAL_ERROR


class ErrorResponse(BaseModel):
    error_id: str = Field(..., description="Machine-readable error code.", examples=["not_found"])
    detail: str
    request_id: str | None = None


COMMON_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorResponse, "description": desc}
    for code, desc in (
        (400, "Bad request"),
        (401, "Unauthorized"),
        (403, "Forbidden"),
        (404, "Not found"),
        (409, "Conflict"),
        (429, "Too many requests"),
        (500, "Internal server error"),
    )
}

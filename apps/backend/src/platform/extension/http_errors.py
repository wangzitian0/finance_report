"""Common exception utilities for FastAPI routers."""

from typing import NoReturn

from fastapi import HTTPException, status


def _raise_http(
    status_code: int,
    detail: str,
    *,
    headers: dict[str, str] | None = None,
    cause: Exception | None = None,
) -> NoReturn:
    raise HTTPException(status_code=status_code, detail=detail, headers=headers) from cause


def raise_not_found(resource_name: str, *, cause: Exception | None = None) -> NoReturn:
    _raise_http(status.HTTP_404_NOT_FOUND, f"{resource_name} not found", cause=cause)


def raise_bad_request(detail: str, *, cause: Exception | None = None) -> NoReturn:
    _raise_http(status.HTTP_400_BAD_REQUEST, detail, cause=cause)


def raise_unauthorized(detail: str, *, cause: Exception | None = None) -> NoReturn:
    _raise_http(status.HTTP_401_UNAUTHORIZED, detail, cause=cause)


def raise_conflict(detail: str, *, cause: Exception | None = None) -> NoReturn:
    _raise_http(status.HTTP_409_CONFLICT, detail, cause=cause)


def raise_too_large(detail: str, *, cause: Exception | None = None) -> NoReturn:
    _raise_http(status.HTTP_413_CONTENT_TOO_LARGE, detail, cause=cause)


def raise_too_many_requests(detail: str, *, retry_after: int | None = None, cause: Exception | None = None) -> NoReturn:
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    _raise_http(status.HTTP_429_TOO_MANY_REQUESTS, detail, headers=headers, cause=cause)


def raise_internal_error(detail: str, *, cause: Exception | None = None) -> NoReturn:
    _raise_http(status.HTTP_500_INTERNAL_SERVER_ERROR, detail, cause=cause)


def raise_service_unavailable(detail: str, *, cause: Exception | None = None) -> NoReturn:
    _raise_http(status.HTTP_503_SERVICE_UNAVAILABLE, detail, cause=cause)


def raise_gateway_timeout(detail: str, *, cause: Exception | None = None) -> NoReturn:
    _raise_http(status.HTTP_504_GATEWAY_TIMEOUT, detail, cause=cause)


class BaseAppException(Exception):
    """Base exception with error_id for structured frontend consumption."""

    def __init__(self, error_id: str, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.status_code = status_code

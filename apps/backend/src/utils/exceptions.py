"""Common exception utilities for FastAPI routers."""

from typing import NoReturn

from fastapi import HTTPException, status


def raise_not_found(resource_name: str, *, cause: Exception | None = None) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{resource_name} not found",
    ) from cause


def raise_bad_request(detail: str, *, cause: Exception | None = None) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=detail,
    ) from cause


def raise_unauthorized(detail: str, *, cause: Exception | None = None) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
    ) from cause


def raise_conflict(detail: str, *, cause: Exception | None = None) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=detail,
    ) from cause


def raise_too_large(detail: str, *, cause: Exception | None = None) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=detail,
    ) from cause


def raise_too_many_requests(detail: str, *, retry_after: int | None = None, cause: Exception | None = None) -> NoReturn:
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers=headers,
    ) from cause


def raise_internal_error(detail: str, *, cause: Exception | None = None) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=detail,
    ) from cause


def raise_service_unavailable(detail: str, *, cause: Exception | None = None) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
    ) from cause


def raise_gateway_timeout(detail: str, *, cause: Exception | None = None) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        detail=detail,
    ) from cause

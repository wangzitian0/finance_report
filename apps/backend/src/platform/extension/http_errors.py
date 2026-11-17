"""Common exception utilities for FastAPI routers."""

from typing import Any, NoReturn

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

    def __init__(
        self,
        error_id: str,
        message: str,
        status_code: int = 500,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.status_code = status_code
        self.extra = extra

    @property
    def detail(self) -> str:
        """HTTP-compatible detail alias for direct handler callers."""
        return self.message


_DOMAIN_ERROR_IDS: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "unprocessable_entity",
}


class DomainError(BaseAppException, ValueError):
    """Domain rule failure that is both a ValueError and an HTTP-mapped BaseAppException."""

    default_status_code: int = status.HTTP_400_BAD_REQUEST
    default_error_id: str | None = None

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        resolved_status = self.default_status_code if status_code is None else status_code
        resolved_error_id = (
            error_id or self.default_error_id or _DOMAIN_ERROR_IDS.get(resolved_status, f"HTTP_{resolved_status}")
        )
        super().__init__(error_id=resolved_error_id, message=message, status_code=resolved_status, extra=extra)


class ValidationFailedError(DomainError):
    """Input or domain invariant validation failed (HTTP 400)."""

    default_status_code = status.HTTP_400_BAD_REQUEST
    default_error_id = "bad_request"


class ResourceNotFoundError(DomainError):
    """Requested resource does not exist or is not visible to caller (HTTP 404)."""

    default_status_code = status.HTTP_404_NOT_FOUND
    default_error_id = "not_found"


class ConflictError(DomainError):
    """Operation conflicts with current resource or concurrency state (HTTP 409)."""

    default_status_code = status.HTTP_409_CONFLICT
    default_error_id = "conflict"


class PreconditionFailedError(DomainError):
    """Request could not proceed under current domain preconditions (HTTP 422)."""

    default_status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    default_error_id = "unprocessable_entity"

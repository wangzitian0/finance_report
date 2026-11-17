"""Pure application and domain exception hierarchy shared across backend packages."""

from __future__ import annotations

from typing import Any


class BaseAppException(Exception):
    """Base exception with error_id and HTTP status metadata for API error serialization."""

    def __init__(
        self,
        error_id: str,
        message: object,
        status_code: int = 500,
        *,
        extra: dict[str, Any] | None = None,
        detail_payload: dict[str, Any] | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        text = message if isinstance(message, str) else str(message)
        super().__init__(text)
        self.error_id = error_id
        self.message = text
        self.status_code = status_code
        self.extra = extra
        self.detail_payload = detail_payload
        self.headers = headers

    @property
    def detail(self) -> dict[str, Any] | str:
        """HTTP-compatible detail alias for direct handler callers."""
        return self.detail_payload if self.detail_payload is not None else self.message


_DOMAIN_ERROR_IDS: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    413: "content_too_large",
    422: "unprocessable_entity",
    429: "too_many_requests",
    500: "internal_error",
    502: "internal_error",
    503: "service_unavailable",
    504: "gateway_timeout",
}


class DomainError(BaseAppException, ValueError):
    """Domain rule failure that is both a ValueError and an HTTP-mapped BaseAppException."""

    default_status_code: int = 400
    default_error_id: str | None = None

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_id: str | None = None,
        extra: dict[str, Any] | None = None,
        detail_payload: dict[str, Any] | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        resolved_status = self.default_status_code if status_code is None else status_code
        resolved_error_id = (
            error_id or self.default_error_id or _DOMAIN_ERROR_IDS.get(resolved_status, f"HTTP_{resolved_status}")
        )
        super().__init__(
            error_id=resolved_error_id,
            message=message,
            status_code=resolved_status,
            extra=extra,
            detail_payload=detail_payload,
            headers=headers,
        )


class ValidationFailedError(DomainError):
    """Input or domain invariant validation failed (HTTP 400)."""

    default_status_code = 400
    default_error_id = "bad_request"


class UnauthorizedError(DomainError):
    """Authentication credentials were missing, invalid, or rejected (HTTP 401)."""

    default_status_code = 401
    default_error_id = "unauthorized"


class ForbiddenError(DomainError):
    """Authenticated caller lacks permission for the requested resource (HTTP 403)."""

    default_status_code = 403
    default_error_id = "forbidden"


class ResourceNotFoundError(DomainError):
    """Requested resource does not exist or is not visible to caller (HTTP 404)."""

    default_status_code = 404
    default_error_id = "not_found"


class ConflictError(DomainError):
    """Operation conflicts with current resource or concurrency state (HTTP 409)."""

    default_status_code = 409
    default_error_id = "conflict"


class ContentTooLargeError(DomainError):
    """Uploaded payload exceeds allowed size limits (HTTP 413)."""

    default_status_code = 413
    default_error_id = "content_too_large"


class PreconditionFailedError(DomainError):
    """Request could not proceed under current domain preconditions (HTTP 422)."""

    default_status_code = 422
    default_error_id = "unprocessable_entity"


class TooManyRequestsError(DomainError):
    """Caller exceeded an allowed request or quota threshold (HTTP 429)."""

    default_status_code = 429
    default_error_id = "too_many_requests"


class InternalServiceError(DomainError):
    """Unexpected server-side invariant or persistence failure (HTTP 500)."""

    default_status_code = 500
    default_error_id = "internal_error"


class BadGatewayError(DomainError):
    """Upstream storage or external dependency returned an invalid failure (HTTP 502)."""

    default_status_code = 502
    default_error_id = "internal_error"


class ServiceUnavailableError(DomainError):
    """Required backing dependency or model service is unavailable (HTTP 503)."""

    default_status_code = 503
    default_error_id = "service_unavailable"


class GatewayTimeoutError(DomainError):
    """Upstream dependency timed out before completing the operation (HTTP 504)."""

    default_status_code = 504
    default_error_id = "gateway_timeout"

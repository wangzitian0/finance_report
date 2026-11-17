"""Exception hierarchy for the LLM abstraction (EPIC-023)."""

from __future__ import annotations

from src.platform.base.errors import DomainError, ServiceUnavailableError


class LLMError(DomainError):
    """Base class for all LLM-layer failures.

    ``retryable`` flags transient conditions (HTTP 429/5xx, mid-stream server
    errors) so callers can decide whether to fall back or retry. It mirrors the
    semantics of the legacy ``AIStreamError`` so existing call sites keep working
    when they delegate into this layer.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        error_id: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, error_id=error_id)
        self.retryable = retryable


class LLMConfigError(ServiceUnavailableError, LLMError):
    """Configuration is missing or invalid (no provider, bad/absent encryption key).

    Never retryable.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class LLMBudgetExceeded(LLMError):
    """A spend guard tripped before or after a call (replaces the daily-limit check).

    Never retryable: retrying would only spend more.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class ModelCatalogError(LLMError):
    """The model catalogue could not be fetched or parsed."""

"""Exception hierarchy of the model entry point: ``LLMError`` and ``ModelCallFailed`` (#3153)."""

from __future__ import annotations

from enum import StrEnum

from src.platform.base.errors import DomainError, ServiceUnavailableError


class LLMError(DomainError):
    """Base class for all LLM-layer failures.

    ``retryable`` flags transient conditions (HTTP 429/5xx, mid-stream server
    errors) so callers can decide whether to fall back or retry.
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
    """Configuration is missing or invalid (no provider, bad or absent key).

    Never retryable.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class ModelFailureKind(StrEnum):
    """Why a model call failed. The values are the metric label and the log field."""

    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"
    USAGE_LIMIT = "usage_limit"
    NOT_CONFIGURED = "not_configured"
    BAD_REPLY = "bad_reply"
    UNCLASSIFIED = "unclassified"


# The HTTP status and the retry flag of each kind.
_KIND_STATUS: dict[ModelFailureKind, tuple[int, bool]] = {
    ModelFailureKind.RATE_LIMIT: (429, True),
    ModelFailureKind.TIMEOUT: (504, True),
    ModelFailureKind.UNAVAILABLE: (503, True),
    ModelFailureKind.REJECTED: (502, False),
    ModelFailureKind.USAGE_LIMIT: (429, False),
    ModelFailureKind.NOT_CONFIGURED: (503, False),
    ModelFailureKind.BAD_REPLY: (502, False),
    ModelFailureKind.UNCLASSIFIED: (502, False),
}


class ModelCallFailed(LLMError):
    """A model call did not give a usable answer. The one error that a call site of the entry point may catch.

    The entry point (``src.llm.extension.agent``) raises it for each failure below the SDK, whatever the SDK made
    of it: the SDK keeps the class of a provider error and turns every other error into a bare ``RuntimeError``.
    ``kind`` says what happened, ``summary`` is the text that the SDK redacted (class, HTTP status, provider code;
    never the prompt). A call site decides what a failure means for its result; it never returns a value that
    looks like an answer.
    """

    def __init__(self, kind: ModelFailureKind, summary: str, *, call_site: str | None = None) -> None:
        status_code, retryable = _KIND_STATUS[kind]
        super().__init__(f"Model call failed ({kind.value}): {summary}", retryable=retryable, status_code=status_code)
        self.kind = kind
        self.summary = summary
        self.call_site = call_site

    def __reduce__(self):
        # ``args`` holds only the message, so the default reduce cannot call ``__init__``: copy and pickle need this.
        return (type(self), (self.kind, self.summary), self.__dict__.copy())

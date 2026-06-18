"""Structured observability event helpers for audit and security logs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import structlog

from src.services.pii_redaction import detect_pii

RISKY_LOG_FIELD_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "cookies",
        "api_key",
        "token",
        "secret",
        "password",
        "prompt",
        "raw_prompt",
        "raw_response",
        "response_body",
        "error_body",
        "provider_body",
        "provider_response",
    }
)
MAX_SAFE_ERROR_CHARS = 300


def _redact_detected_pii(text: str) -> str:
    matches = detect_pii(text)
    if not matches:
        return text

    redacted = text
    for match in sorted(matches, key=lambda item: item.start, reverse=True):
        label = f"[{match.pii_type.value.upper()}]"
        redacted = redacted[: match.start] + label + redacted[match.end :]
    return redacted


def bind_authenticated_user_context(user_id: UUID | str) -> None:
    """Bind the authenticated user id into structlog contextvars."""
    structlog.contextvars.bind_contextvars(user_id=str(user_id))


def current_request_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("request_id")
    return str(value) if value else None


def safe_error_message(message: object, *, limit: int = MAX_SAFE_ERROR_CHARS) -> str:
    """Return a one-line bounded error summary that is safe for logs."""
    text = _redact_detected_pii(" ".join(str(message).split()))
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def safe_log_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Return log fields with risky raw body/secret keys redacted."""
    safe: dict[str, Any] = {}
    for key, value in fields.items():
        normalized = key.lower()
        if normalized in RISKY_LOG_FIELD_NAMES:
            safe[key] = "[REDACTED]"
        elif isinstance(value, Mapping):
            safe[key] = safe_log_fields(value)
        else:
            safe[key] = value
    return safe


def log_financial_mutation(
    logger: Any,
    event: str,
    *,
    user_id: UUID | str,
    action: str,
    resource_type: str,
    resource_id: UUID | str,
    **fields: Any,
) -> None:
    """Emit one financial mutation audit event with stable common fields."""
    logger.info(
        event,
        **safe_log_fields(
            {
                "audit_event": event,
                "user_id": str(user_id),
                "request_id": current_request_id(),
                "action": action,
                "resource_type": resource_type,
                "resource_id": str(resource_id),
                **fields,
            }
        ),
    )


def log_security_warning(
    logger: Any,
    event: str,
    *,
    reason: str,
    user_id: UUID | str | None = None,
    client_ip: str | None = None,
    **fields: Any,
) -> None:
    """Emit one security-relevant warning without raw credentials or payloads."""
    payload: dict[str, Any] = {
        "audit_event": event,
        "request_id": current_request_id(),
        "reason": reason,
    }
    if user_id is not None:
        payload["user_id"] = str(user_id)
    if client_ip is not None:
        payload["client_ip"] = client_ip
    payload.update(fields)
    logger.warning(event, **safe_log_fields(payload))

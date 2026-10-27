"""Internal action link check shared by the reporting and workflow schemas."""

from __future__ import annotations

__all__ = ["validate_internal_action_href"]


def validate_internal_action_href(value: str) -> str:
    """Return ``value`` when it is an internal relative path, else raise ``ValueError``."""
    if not value.startswith("/") or value.startswith("//") or "://" in value:
        raise ValueError("action_href must be an internal relative path")
    return value

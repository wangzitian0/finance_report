"""Identity-owned AI-settings wire vocabulary."""

from pydantic import BaseModel


class UserAiSettingsUpdate(BaseModel):
    """AI feature flag settings that can be overridden per user."""

    enable_ai_reconciliation: bool | None = None
    enable_ai_classification: bool | None = None
    auto_accept_ai_suggestions: bool | None = None


class UserAiSettingsResponse(BaseModel):
    """Effective AI feature settings for the current user."""

    enable_ai_reconciliation: bool
    enable_ai_classification: bool
    #: What the user chose. A user without a choice gets True.
    auto_accept_ai_suggestions: bool
    #: What the system uses: the choice, AI classification, and the process flag of the operator together.
    auto_accept_ai_suggestions_active: bool


__all__ = [
    "UserAiSettingsResponse",
    "UserAiSettingsUpdate",
]

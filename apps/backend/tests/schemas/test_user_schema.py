import pytest
from pydantic import ValidationError
from src.identity import UserAiSettingsResponse, UserAiSettingsUpdate


def test_user_ai_settings_update_partial():
    empty, partial = UserAiSettingsUpdate(), UserAiSettingsUpdate(enable_ai_reconciliation=True)
    resp = UserAiSettingsResponse(
        enable_ai_reconciliation=True,
        enable_ai_classification=False,
        auto_accept_ai_suggestions=True,
        auto_accept_ai_suggestions_active=False,
    )
    assert (
        empty.enable_ai_reconciliation,
        empty.enable_ai_classification,
        partial.enable_ai_reconciliation,
        partial.enable_ai_classification,
    ) == (None, None, True, None)
    assert (
        resp.enable_ai_reconciliation,
        resp.enable_ai_classification,
        resp.auto_accept_ai_suggestions,
        resp.auto_accept_ai_suggestions_active,
    ) == (True, False, True, False)
    assert "auto_accept_ai_suggestions_active" not in UserAiSettingsUpdate.model_fields
    with pytest.raises(ValidationError):
        UserAiSettingsResponse(enable_ai_reconciliation=True)


@pytest.mark.parametrize("missing", ["auto_accept_ai_suggestions", "auto_accept_ai_suggestions_active"])
def test_user_ai_settings_response_needs_the_choice_and_the_value_in_use(missing):
    values = {
        "enable_ai_reconciliation": True,
        "enable_ai_classification": False,
        "auto_accept_ai_suggestions": True,
        "auto_accept_ai_suggestions_active": False,
    }
    del values[missing]
    with pytest.raises(ValidationError):
        UserAiSettingsResponse(**values)

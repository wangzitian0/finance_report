import pytest; from pydantic import ValidationError; from src.identity import UserAiSettingsResponse, UserAiSettingsUpdate
def test_user_ai_settings_update_partial():
    _m3_s = UserAiSettingsUpdate(); assert _m3_s.enable_ai_reconciliation is None; assert _m3_s.enable_ai_classification is None; _m4_s = UserAiSettingsUpdate(enable_ai_reconciliation=True); assert _m4_s.enable_ai_reconciliation is True; assert _m4_s.enable_ai_classification is None; _m5_r = UserAiSettingsResponse(enable_ai_reconciliation=True, enable_ai_classification=False, auto_accept_ai_suggestions=True, auto_accept_ai_suggestions_active=False); assert _m5_r.enable_ai_reconciliation is True; assert _m5_r.enable_ai_classification is False; assert _m5_r.auto_accept_ai_suggestions is True; assert _m5_r.auto_accept_ai_suggestions_active is False; assert 'auto_accept_ai_suggestions_active' not in UserAiSettingsUpdate.model_fields
    with pytest.raises(ValidationError): UserAiSettingsResponse(enable_ai_reconciliation=True)
@pytest.mark.parametrize('missing', ['auto_accept_ai_suggestions', 'auto_accept_ai_suggestions_active'])
def test_user_ai_settings_response_needs_the_choice_and_the_value_in_use(missing):
    values = {'enable_ai_reconciliation': True, 'enable_ai_classification': False, 'auto_accept_ai_suggestions': True, 'auto_accept_ai_suggestions_active': False}; del values[missing]
    with pytest.raises(ValidationError): UserAiSettingsResponse(**values)

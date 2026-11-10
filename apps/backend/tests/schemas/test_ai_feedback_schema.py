from datetime import datetime; from uuid import uuid4; import pytest; from pydantic import ValidationError; from src.identity import AiFeedbackRequest, AiFeedbackResponse, AiSuggestionListResponse, AiSuggestionResponse
def test_ai_feedback_request_accept_valid():
    sid = uuid4(); req = AiFeedbackRequest(suggestion_id=sid, action='accept'); assert req.action == 'accept'; assert req.corrected_value is None; _m1_req = AiFeedbackRequest(suggestion_id=uuid4(), action='edit_accept', corrected_value={'category': 'Food'}); assert _m1_req.corrected_value == {'category': 'Food'}
    with pytest.raises(ValidationError): AiFeedbackRequest(suggestion_id=uuid4(), action='ignore')
    with pytest.raises(ValidationError): AiFeedbackRequest(suggestion_id='not-a-uuid', action='accept')
    _m4_payload = {'id': uuid4(), 'suggestion_id': uuid4(), 'user_id': uuid4(), 'action': 'accept', 'corrected_value': None, 'created_at': datetime(2025, 1, 1, 12, 0, 0)}; _m4_resp = AiFeedbackResponse.model_validate(_m4_payload); assert _m4_resp.action == 'accept'; _m5_s = AiSuggestionResponse(suggestion_id=uuid4(), transaction='GRAB *FOOD', suggested_category_or_match='Food', ai_score=72, ai_reasoning='merchant token match'); assert _m5_s.ai_score == 72; _m6_lst = AiSuggestionListResponse(items=[], total=0); assert _m6_lst.total == 0
@pytest.mark.parametrize('bad_score', [59, 85, 0, 100])
def test_ai_suggestion_response_score_out_of_range(bad_score):
    with pytest.raises(ValidationError): AiSuggestionResponse(suggestion_id=uuid4(), transaction='X', suggested_category_or_match='Y', ai_score=bad_score, ai_reasoning='r')

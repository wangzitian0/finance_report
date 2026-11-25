from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from src.schemas.extraction import AiFeedbackRequest, AiFeedbackResponse, AiSuggestionListResponse, AiSuggestionResponse


def test_ai_feedback_and_suggestion_schemas():
    accept = AiFeedbackRequest(suggestion_id=uuid4(), action="accept")
    edit = AiFeedbackRequest(suggestion_id=uuid4(), action="edit_accept", corrected_value={"category": "Food"})
    assert (accept.action, accept.corrected_value, edit.corrected_value) == ("accept", None, {"category": "Food"})
    for bad in ({"suggestion_id": uuid4(), "action": "ignore"}, {"suggestion_id": "not-a-uuid", "action": "accept"}):
        with pytest.raises(ValidationError):
            AiFeedbackRequest(**bad)

    resp = AiFeedbackResponse.model_validate(
        {
            "id": uuid4(),
            "suggestion_id": uuid4(),
            "user_id": uuid4(),
            "action": "accept",
            "corrected_value": None,
            "created_at": datetime(2025, 1, 1, 12, 0, 0),
        }
    )
    suggestion = AiSuggestionResponse(
        suggestion_id=uuid4(),
        transaction="GRAB *FOOD",
        suggested_category_or_match="Food",
        ai_score=72,
        ai_reasoning="merchant token match",
    )
    assert (resp.action, suggestion.ai_score, AiSuggestionListResponse(items=[], total=0).total) == ("accept", 72, 0)


@pytest.mark.parametrize("bad_score", [59, 85, 0, 100])
def test_ai_suggestion_response_score_out_of_range(bad_score):
    with pytest.raises(ValidationError):
        AiSuggestionResponse(
            suggestion_id=uuid4(),
            transaction="X",
            suggested_category_or_match="Y",
            ai_score=bad_score,
            ai_reasoning="r",
        )

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.identity import (
    AiFeedbackRequest,
    AiFeedbackResponse,
    AiSuggestionListResponse,
    AiSuggestionResponse,
)


def test_ai_feedback_request_accept_valid():
    sid = uuid4()
    req = AiFeedbackRequest(suggestion_id=sid, action="accept")
    assert req.action == "accept"
    assert req.corrected_value is None


def test_ai_feedback_request_edit_accept_with_correction():
    req = AiFeedbackRequest(
        suggestion_id=uuid4(),
        action="edit_accept",
        corrected_value={"category": "Food"},
    )
    assert req.corrected_value == {"category": "Food"}


def test_ai_feedback_request_invalid_action_rejected():
    with pytest.raises(ValidationError):
        AiFeedbackRequest(suggestion_id=uuid4(), action="ignore")


def test_ai_feedback_request_invalid_uuid_rejected():
    with pytest.raises(ValidationError):
        AiFeedbackRequest(suggestion_id="not-a-uuid", action="accept")


def test_ai_feedback_response_from_attributes():
    payload = {
        "id": uuid4(),
        "suggestion_id": uuid4(),
        "user_id": uuid4(),
        "action": "accept",
        "corrected_value": None,
        "created_at": datetime(2025, 1, 1, 12, 0, 0),
    }
    resp = AiFeedbackResponse.model_validate(payload)
    assert resp.action == "accept"


def test_ai_suggestion_response_score_in_range():
    s = AiSuggestionResponse(
        suggestion_id=uuid4(),
        transaction="GRAB *FOOD",
        suggested_category_or_match="Food",
        ai_score=72,
        ai_reasoning="merchant token match",
    )
    assert s.ai_score == 72


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


def test_ai_suggestion_list_response_empty():
    lst = AiSuggestionListResponse(items=[], total=0)
    assert lst.total == 0

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.schemas.user import (
    UserAiSettingsResponse,
    UserAiSettingsUpdate,
    UserResponse,
    UserUpdate,
)


def test_user_update_partial():
    u = UserUpdate(email="new@b.com")
    assert u.email == "new@b.com"
    assert UserUpdate().email is None


def test_user_response_naive_datetime_made_aware():
    naive = datetime(2025, 1, 1, 12, 0, 0)
    resp = UserResponse(
        id=uuid4(),
        email="a@b.com",
        created_at=naive,
        updated_at=naive,
    )
    assert resp.created_at.tzinfo is UTC
    assert resp.updated_at.tzinfo is UTC


def test_user_response_aware_datetime_preserved():
    aware = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    resp = UserResponse(
        id=uuid4(),
        email="a@b.com",
        created_at=aware,
        updated_at=aware,
    )
    assert resp.created_at == aware


def test_user_ai_settings_update_defaults_none():
    s = UserAiSettingsUpdate()
    assert s.enable_ai_reconciliation is None
    assert s.enable_ai_classification is None


def test_user_ai_settings_update_partial():
    s = UserAiSettingsUpdate(enable_ai_reconciliation=True)
    assert s.enable_ai_reconciliation is True
    assert s.enable_ai_classification is None


def test_user_ai_settings_response_required_booleans():
    r = UserAiSettingsResponse(
        enable_ai_reconciliation=True,
        enable_ai_classification=False,
        auto_accept_ai_suggestions=True,
        auto_accept_ai_suggestions_active=False,
    )
    assert r.enable_ai_reconciliation is True
    assert r.enable_ai_classification is False
    assert r.auto_accept_ai_suggestions is True
    assert r.auto_accept_ai_suggestions_active is False


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


def test_user_ai_settings_update_cannot_set_the_value_in_use():
    assert "auto_accept_ai_suggestions_active" not in UserAiSettingsUpdate.model_fields


def test_user_ai_settings_response_missing_field_rejected():
    with pytest.raises(ValidationError):
        UserAiSettingsResponse(enable_ai_reconciliation=True)

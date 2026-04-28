from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.schemas.user import (
    UserAiSettingsResponse,
    UserAiSettingsUpdate,
    UserCreate,
    UserResponse,
    UserUpdate,
)


def test_user_create_valid():
    u = UserCreate(email="a@b.com", password="password123")
    assert u.email == "a@b.com"


def test_user_create_password_too_short():
    with pytest.raises(ValidationError):
        UserCreate(email="a@b.com", password="short")


def test_user_create_password_too_long():
    with pytest.raises(ValidationError):
        UserCreate(email="a@b.com", password="x" * 129)


def test_user_create_invalid_email():
    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", password="password123")


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
    )
    assert r.enable_ai_reconciliation is True
    assert r.enable_ai_classification is False


def test_user_ai_settings_response_missing_field_rejected():
    with pytest.raises(ValidationError):
        UserAiSettingsResponse(enable_ai_reconciliation=True)

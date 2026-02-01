"""Tests for security utilities (JWT token creation and validation)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest

from src.config import settings
from src.security import create_access_token, decode_access_token


def test_create_access_token_with_custom_expiry():
    """
    GIVEN a data payload and custom expiry delta
    WHEN creating an access token
    THEN the token should contain the data and custom expiry
    """
    data = {"sub": "user123"}
    expires_delta = timedelta(hours=2)

    token = create_access_token(data, expires_delta)

    decoded = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    assert decoded["sub"] == "user123"
    assert "exp" in decoded


def test_create_access_token_with_default_expiry():
    """
    GIVEN a data payload without custom expiry
    WHEN creating an access token
    THEN the token should use default expiry from settings
    """
    data = {"sub": "user456"}

    token = create_access_token(data)

    decoded = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    assert decoded["sub"] == "user456"
    assert "exp" in decoded

    exp_datetime = datetime.fromtimestamp(decoded["exp"], tz=UTC)
    expected_exp = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)

    assert abs((exp_datetime - expected_exp).total_seconds()) < 2


def test_decode_access_token_valid():
    """
    GIVEN a valid JWT token
    WHEN decoding the token
    THEN it should return the payload
    """
    data = {"sub": "user789", "role": "admin"}
    token = create_access_token(data)

    payload = decode_access_token(token)

    assert payload is not None
    assert payload["sub"] == "user789"
    assert payload["role"] == "admin"


def test_decode_access_token_expired():
    """
    GIVEN an expired JWT token
    WHEN decoding the token
    THEN it should return None and log debug message
    """
    data = {"sub": "expired_user"}
    expires_delta = timedelta(seconds=-1)
    token = create_access_token(data, expires_delta)

    with patch("src.security.logger.debug") as mock_debug:
        payload = decode_access_token(token)

    assert payload is None
    mock_debug.assert_called_once_with("JWT token expired")


def test_decode_access_token_invalid_signature():
    """
    GIVEN a JWT token with invalid signature
    WHEN decoding the token
    THEN it should return None and log warning
    """
    data = {"sub": "user999"}
    token = jwt.encode(data, "wrong-secret", algorithm="HS256")

    with patch("src.security.logger.warning") as mock_warning:
        payload = decode_access_token(token)

    assert payload is None
    mock_warning.assert_called_once()
    call_args = mock_warning.call_args
    assert "JWT decode failed" in str(call_args)


def test_decode_access_token_malformed():
    """
    GIVEN a malformed JWT token
    WHEN decoding the token
    THEN it should return None and log warning
    """
    token = "not.a.valid.jwt.token"

    with patch("src.security.logger.warning") as mock_warning:
        payload = decode_access_token(token)

    assert payload is None
    mock_warning.assert_called_once()

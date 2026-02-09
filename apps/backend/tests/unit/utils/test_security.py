import pytest
from datetime import timedelta, UTC, datetime
from src.security import create_access_token, decode_access_token
from src.config import settings

def test_create_and_decode_access_token():
    """AC8.2.3: Verify token creation and decoding with default expiration."""
    data = {"sub": "user_123", "role": "admin"}
    token = create_access_token(data)
    assert isinstance(token, str)
    
    payload = decode_access_token(token)
    assert payload["sub"] == "user_123"
    assert payload["role"] == "admin"
    assert "exp" in payload

def test_create_access_token_with_custom_expiry():
    """AC8.2.3: Verify token creation with custom expiration."""
    expires_delta = timedelta(minutes=10)
    data = {"sub": "user_456"}
    token = create_access_token(data, expires_delta=expires_delta)
    
    payload = decode_access_token(token)
    assert payload["sub"] == "user_456"
    
    # Verify exp is approx 10 mins from now
    exp_timestamp = payload["exp"]
    expected_exp = datetime.now(UTC) + expires_delta
    assert abs(exp_timestamp - expected_exp.timestamp()) < 5

def test_decode_expired_token():
    """AC8.2.3: Verify handling of expired tokens."""
    expires_delta = timedelta(seconds=-1) # Already expired
    data = {"sub": "user_789"}
    token = create_access_token(data, expires_delta=expires_delta)
    
    payload = decode_access_token(token)
    assert payload is None

def test_decode_invalid_token():
    """AC8.2.3: Verify handling of malformed tokens."""
    assert decode_access_token("invalid.token.string") is None
    assert decode_access_token("") is None

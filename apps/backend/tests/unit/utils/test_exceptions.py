import pytest
from fastapi import HTTPException, status
from src.utils.exceptions import (
    raise_not_found,
    raise_bad_request,
    raise_unauthorized,
    raise_conflict,
    raise_too_large,
    raise_too_many_requests,
    raise_internal_error,
    raise_service_unavailable,
    raise_gateway_timeout
)

def test_raise_not_found():
    """AC0.1.1: Verify 404 exception raising."""
    with pytest.raises(HTTPException) as exc:
        raise_not_found("TestResource")
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == "TestResource not found"

def test_raise_bad_request():
    """AC0.1.2: Verify 400 exception raising."""
    with pytest.raises(HTTPException) as exc:
        raise_bad_request("bad stuff")
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc.value.detail == "bad stuff"

def test_raise_unauthorized():
    """AC0.1.3: Verify 401 exception raising."""
    with pytest.raises(HTTPException) as exc:
        raise_unauthorized("no access")
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "no access"

def test_raise_conflict():
    """AC0.1.4: Verify 409 exception raising."""
    with pytest.raises(HTTPException) as exc:
        raise_conflict("already exists")
    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert exc.value.detail == "already exists"

def test_raise_too_large():
    """AC0.1.5: Verify 413 exception raising."""
    with pytest.raises(HTTPException) as exc:
        raise_too_large("too big")
    assert exc.value.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert exc.value.detail == "too big"

def test_raise_too_many_requests():
    """AC0.1.6: Verify 429 exception raising with headers."""
    with pytest.raises(HTTPException) as exc:
        raise_too_many_requests("slow down", retry_after=60)
    assert exc.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert exc.value.detail == "slow down"
    assert exc.value.headers["Retry-After"] == "60"

def test_raise_internal_error():
    """AC0.1.7: Verify 500 exception raising."""
    with pytest.raises(HTTPException) as exc:
        raise_internal_error("boom")
    assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc.value.detail == "boom"

def test_raise_service_unavailable():
    """AC0.1.8: Verify 503 exception raising."""
    with pytest.raises(HTTPException) as exc:
        raise_service_unavailable("offline")
    assert exc.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc.value.detail == "offline"

def test_raise_gateway_timeout():
    """AC0.1.9: Verify 504 exception raising."""
    with pytest.raises(HTTPException) as exc:
        raise_gateway_timeout("timeout")
    assert exc.value.status_code == status.HTTP_504_GATEWAY_TIMEOUT
    assert exc.value.detail == "timeout"

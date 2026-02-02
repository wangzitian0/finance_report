"""Tests for exception utilities."""

import pytest
from fastapi import HTTPException, status

from src.utils.exceptions import (
    raise_bad_request,
    raise_conflict,
    raise_gateway_timeout,
    raise_internal_error,
    raise_not_found,
    raise_service_unavailable,
    raise_too_large,
    raise_too_many_requests,
    raise_unauthorized,
)


def test_raise_not_found():
    """
    GIVEN a resource name
    WHEN raise_not_found is called
    THEN it should raise HTTPException with 404 status
    """
    with pytest.raises(HTTPException) as exc_info:
        raise_not_found("User")

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "User not found"


def test_raise_not_found_with_cause():
    """
    GIVEN a resource name and a cause exception
    WHEN raise_not_found is called
    THEN it should raise HTTPException with the cause attached
    """
    cause = ValueError("Original error")

    with pytest.raises(HTTPException) as exc_info:
        raise_not_found("Account", cause=cause)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.__cause__ is cause


def test_raise_bad_request():
    """
    GIVEN a detail message
    WHEN raise_bad_request is called
    THEN it should raise HTTPException with 400 status
    """
    with pytest.raises(HTTPException) as exc_info:
        raise_bad_request("Invalid input")

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid input"


def test_raise_bad_request_with_cause():
    """
    GIVEN a detail message and cause
    WHEN raise_bad_request is called
    THEN it should raise HTTPException with the cause attached
    """
    cause = ValueError("Validation failed")

    with pytest.raises(HTTPException) as exc_info:
        raise_bad_request("Bad data", cause=cause)

    assert exc_info.value.__cause__ is cause


def test_raise_unauthorized():
    """
    GIVEN a detail message
    WHEN raise_unauthorized is called
    THEN it should raise HTTPException with 401 status
    """
    with pytest.raises(HTTPException) as exc_info:
        raise_unauthorized("Invalid token")

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Invalid token"


def test_raise_unauthorized_with_cause():
    """
    GIVEN a detail message and cause
    WHEN raise_unauthorized is called
    THEN it should raise HTTPException with the cause attached
    """
    cause = RuntimeError("Token expired")

    with pytest.raises(HTTPException) as exc_info:
        raise_unauthorized("Unauthorized", cause=cause)

    assert exc_info.value.__cause__ is cause


def test_raise_conflict():
    """
    GIVEN a detail message
    WHEN raise_conflict is called
    THEN it should raise HTTPException with 409 status
    """
    with pytest.raises(HTTPException) as exc_info:
        raise_conflict("Resource already exists")

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "Resource already exists"


def test_raise_conflict_with_cause():
    """
    GIVEN a detail message and cause
    WHEN raise_conflict is called
    THEN it should raise HTTPException with the cause attached
    """
    cause = RuntimeError("Duplicate key")

    with pytest.raises(HTTPException) as exc_info:
        raise_conflict("Conflict", cause=cause)

    assert exc_info.value.__cause__ is cause


def test_raise_too_large():
    """
    GIVEN a detail message
    WHEN raise_too_large is called
    THEN it should raise HTTPException with 413 status
    """
    with pytest.raises(HTTPException) as exc_info:
        raise_too_large("File too large")

    assert exc_info.value.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert exc_info.value.detail == "File too large"


def test_raise_too_large_with_cause():
    """
    GIVEN a detail message and cause
    WHEN raise_too_large is called
    THEN it should raise HTTPException with the cause attached
    """
    cause = ValueError("Size exceeded")

    with pytest.raises(HTTPException) as exc_info:
        raise_too_large("Too large", cause=cause)

    assert exc_info.value.__cause__ is cause


def test_raise_too_many_requests():
    """
    GIVEN a detail message
    WHEN raise_too_many_requests is called
    THEN it should raise HTTPException with 429 status
    """
    with pytest.raises(HTTPException) as exc_info:
        raise_too_many_requests("Rate limit exceeded")

    assert exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert exc_info.value.detail == "Rate limit exceeded"


def test_raise_too_many_requests_with_retry_after():
    """
    GIVEN a detail message and retry_after value
    WHEN raise_too_many_requests is called
    THEN it should raise HTTPException with Retry-After header
    """
    with pytest.raises(HTTPException) as exc_info:
        raise_too_many_requests("Rate limit exceeded", retry_after=60)

    assert exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert exc_info.value.headers == {"Retry-After": "60"}


def test_raise_too_many_requests_with_cause():
    """
    GIVEN a detail message and cause
    WHEN raise_too_many_requests is called
    THEN it should raise HTTPException with the cause attached
    """
    cause = RuntimeError("Rate limited")

    with pytest.raises(HTTPException) as exc_info:
        raise_too_many_requests("Too many requests", cause=cause)

    assert exc_info.value.__cause__ is cause


def test_raise_internal_error():
    """
    GIVEN a detail message
    WHEN raise_internal_error is called
    THEN it should raise HTTPException with 500 status
    """
    with pytest.raises(HTTPException) as exc_info:
        raise_internal_error("Internal server error")

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Internal server error"


def test_raise_internal_error_with_cause():
    """
    GIVEN a detail message and cause
    WHEN raise_internal_error is called
    THEN it should raise HTTPException with the cause attached
    """
    cause = Exception("Database error")

    with pytest.raises(HTTPException) as exc_info:
        raise_internal_error("Server error", cause=cause)

    assert exc_info.value.__cause__ is cause


def test_raise_service_unavailable():
    """
    GIVEN a detail message
    WHEN raise_service_unavailable is called
    THEN it should raise HTTPException with 503 status
    """
    with pytest.raises(HTTPException) as exc_info:
        raise_service_unavailable("Service unavailable")

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc_info.value.detail == "Service unavailable"


def test_raise_service_unavailable_with_cause():
    """
    GIVEN a detail message and cause
    WHEN raise_service_unavailable is called
    THEN it should raise HTTPException with the cause attached
    """
    cause = ConnectionError("Service down")

    with pytest.raises(HTTPException) as exc_info:
        raise_service_unavailable("Unavailable", cause=cause)

    assert exc_info.value.__cause__ is cause


def test_raise_gateway_timeout():
    """
    GIVEN a detail message
    WHEN raise_gateway_timeout is called
    THEN it should raise HTTPException with 504 status
    """
    with pytest.raises(HTTPException) as exc_info:
        raise_gateway_timeout("Gateway timeout")

    assert exc_info.value.status_code == status.HTTP_504_GATEWAY_TIMEOUT
    assert exc_info.value.detail == "Gateway timeout"


def test_raise_gateway_timeout_with_cause():
    """
    GIVEN a detail message and cause
    WHEN raise_gateway_timeout is called
    THEN it should raise HTTPException with the cause attached
    """
    cause = TimeoutError("Request timeout")

    with pytest.raises(HTTPException) as exc_info:
        raise_gateway_timeout("Timeout", cause=cause)

    assert exc_info.value.__cause__ is cause

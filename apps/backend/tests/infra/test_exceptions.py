"""Unit tests for exception utilities."""

import pytest
from fastapi import HTTPException

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


class TestRaiseNotFound:
    def test_basic_usage(self):
        with pytest.raises(HTTPException) as exc_info:
            raise_not_found("Account")
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Account not found"

    def test_preserves_cause(self):
        original = ValueError("Original error")
        with pytest.raises(HTTPException) as exc_info:
            raise_not_found("Account", cause=original)
        assert exc_info.value.status_code == 404
        assert exc_info.value.__cause__ is original


class TestRaiseBadRequest:
    def test_basic_usage(self):
        with pytest.raises(HTTPException) as exc_info:
            raise_bad_request("Invalid input")
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid input"

    def test_preserves_cause(self):
        original = ValueError("Validation failed")
        with pytest.raises(HTTPException) as exc_info:
            raise_bad_request("Invalid input", cause=original)
        assert exc_info.value.status_code == 400
        assert exc_info.value.__cause__ is original


class TestRaiseUnauthorized:
    def test_basic_usage(self):
        with pytest.raises(HTTPException) as exc_info:
            raise_unauthorized("Invalid credentials")
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid credentials"

    def test_preserves_cause(self):
        original = PermissionError("Access denied")
        with pytest.raises(HTTPException) as exc_info:
            raise_unauthorized("Invalid credentials", cause=original)
        assert exc_info.value.status_code == 401
        assert exc_info.value.__cause__ is original


class TestRaiseConflict:
    def test_basic_usage(self):
        with pytest.raises(HTTPException) as exc_info:
            raise_conflict("Resource already exists")
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "Resource already exists"

    def test_preserves_cause(self):
        original = ValueError("Duplicate key")
        with pytest.raises(HTTPException) as exc_info:
            raise_conflict("Resource already exists", cause=original)
        assert exc_info.value.status_code == 409
        assert exc_info.value.__cause__ is original


class TestRaiseTooLarge:
    def test_basic_usage(self):
        with pytest.raises(HTTPException) as exc_info:
            raise_too_large("File exceeds 10MB limit")
        assert exc_info.value.status_code == 413
        assert exc_info.value.detail == "File exceeds 10MB limit"

    def test_preserves_cause(self):
        original = ValueError("Size exceeded")
        with pytest.raises(HTTPException) as exc_info:
            raise_too_large("File exceeds 10MB limit", cause=original)
        assert exc_info.value.status_code == 413
        assert exc_info.value.__cause__ is original


class TestRaiseTooManyRequests:
    def test_basic_usage(self):
        with pytest.raises(HTTPException) as exc_info:
            raise_too_many_requests("Rate limit exceeded")
        assert exc_info.value.status_code == 429
        assert exc_info.value.detail == "Rate limit exceeded"
        assert exc_info.value.headers is None

    def test_with_retry_after(self):
        with pytest.raises(HTTPException) as exc_info:
            raise_too_many_requests("Rate limit exceeded", retry_after=60)
        assert exc_info.value.status_code == 429
        assert exc_info.value.headers == {"Retry-After": "60"}

    def test_preserves_cause(self):
        original = RuntimeError("Throttled")
        with pytest.raises(HTTPException) as exc_info:
            raise_too_many_requests("Rate limit exceeded", cause=original)
        assert exc_info.value.status_code == 429
        assert exc_info.value.__cause__ is original

    def test_with_retry_after_and_cause(self):
        original = RuntimeError("Throttled")
        with pytest.raises(HTTPException) as exc_info:
            raise_too_many_requests("Rate limit exceeded", retry_after=30, cause=original)
        assert exc_info.value.status_code == 429
        assert exc_info.value.headers == {"Retry-After": "30"}
        assert exc_info.value.__cause__ is original


class TestRaiseInternalError:
    def test_basic_usage(self):
        with pytest.raises(HTTPException) as exc_info:
            raise_internal_error("Unexpected error")
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Unexpected error"

    def test_preserves_cause(self):
        original = RuntimeError("Database connection failed")
        with pytest.raises(HTTPException) as exc_info:
            raise_internal_error("Unexpected error", cause=original)
        assert exc_info.value.status_code == 500
        assert exc_info.value.__cause__ is original


class TestRaiseServiceUnavailable:
    def test_basic_usage(self):
        with pytest.raises(HTTPException) as exc_info:
            raise_service_unavailable("Service down")
        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "Service down"

    def test_preserves_cause(self):
        original = ConnectionError("Cannot reach API")
        with pytest.raises(HTTPException) as exc_info:
            raise_service_unavailable("Service down", cause=original)
        assert exc_info.value.status_code == 503
        assert exc_info.value.__cause__ is original


class TestRaiseGatewayTimeout:
    def test_basic_usage(self):
        with pytest.raises(HTTPException) as exc_info:
            raise_gateway_timeout("Request timed out")
        assert exc_info.value.status_code == 504
        assert exc_info.value.detail == "Request timed out"

    def test_preserves_cause(self):
        original = TimeoutError("Connection timeout")
        with pytest.raises(HTTPException) as exc_info:
            raise_gateway_timeout("Request timed out", cause=original)
        assert exc_info.value.status_code == 504
        assert exc_info.value.__cause__ is original

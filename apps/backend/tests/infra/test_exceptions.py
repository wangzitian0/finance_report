from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src import platform as platform_pkg
from src.platform import (
    BadGatewayError,
    BaseAppException,
    ConflictError,
    ContentTooLargeError,
    DomainError,
    ForbiddenError,
    GatewayTimeoutError,
    InternalServiceError,
    PreconditionFailedError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    TooManyRequestsError,
    UnauthorizedError,
    ValidationFailedError,
)


class TestBaseAppException:
    def test_base_app_exception_fields_and_raise(self) -> None:
        default_exc = BaseAppException(error_id="ERR_003", message="error")
        assert isinstance(default_exc, Exception) and (default_exc.error_id, default_exc.status_code) == (
            "ERR_003",
            500,
        )
        with pytest.raises(BaseAppException) as exc_info:
            raise BaseAppException(error_id="ERR_004", message="raised!", status_code=422)
        assert (exc_info.value.error_id, exc_info.value.status_code, exc_info.value.message, str(exc_info.value)) == (
            "ERR_004",
            422,
            "raised!",
            "raised!",
        )

    @pytest.mark.parametrize(
        ("cls", "expected_status", "expected_error_id"),
        [
            (DomainError, 400, "bad_request"),
            (ValidationFailedError, 400, "bad_request"),
            (UnauthorizedError, 401, "unauthorized"),
            (ForbiddenError, 403, "forbidden"),
            (ResourceNotFoundError, 404, "not_found"),
            (ConflictError, 409, "conflict"),
            (ContentTooLargeError, 413, "content_too_large"),
            (PreconditionFailedError, 422, "unprocessable_entity"),
            (TooManyRequestsError, 429, "too_many_requests"),
            (InternalServiceError, 500, "internal_error"),
            (BadGatewayError, 502, "internal_error"),
            (ServiceUnavailableError, 503, "service_unavailable"),
            (GatewayTimeoutError, 504, "gateway_timeout"),
        ],
    )
    def test_domain_error_subclasses_bridge_value_error_and_base_app_exception(
        self, cls, expected_status, expected_error_id
    ) -> None:
        exc = cls("domain rule failed")
        assert isinstance(exc, DomainError) and isinstance(exc, BaseAppException) and isinstance(exc, ValueError)
        assert (str(exc), exc.message, exc.status_code, exc.error_id) == (
            "domain rule failed",
            "domain rule failed",
            expected_status,
            expected_error_id,
        )

    async def test_base_app_exception_handler_serializes_json_and_headers(self) -> None:
        from src.main import base_app_exception_handler

        resp = await base_app_exception_handler(
            MagicMock(), BaseAppException(error_id="TEST_ERR", message="test message", status_code=422)
        )
        body = json.loads(resp.body)
        assert resp.status_code == 422 and body["error_id"] == "TEST_ERR" and body["detail"] == "test message"

        payload = {"error": "evidence_authority_revoked", "message": "revoked"}
        conflict_exc = ConflictError("revoked", detail_payload=payload)
        assert conflict_exc.detail == payload
        conflict_resp = await base_app_exception_handler(MagicMock(), conflict_exc)
        cbody = json.loads(conflict_resp.body)
        assert conflict_resp.status_code == 409 and cbody["error_id"] == "conflict" and cbody["detail"] == payload

        for exc, status_code, header, expected in (
            (
                UnauthorizedError("Not authenticated", headers={"WWW-Authenticate": "Bearer"}),
                401,
                "www-authenticate",
                "Bearer",
            ),
            (TooManyRequestsError("Slow down", headers={"Retry-After": "42"}), 429, "retry-after", "42"),
        ):
            r = await base_app_exception_handler(MagicMock(), exc)
            assert (r.status_code, r.headers.get(header)) == (status_code, expected)

    def test_legacy_procedural_http_helpers_removed_from_platform(self) -> None:
        obsolete = (
            "raise_bad_request",
            "raise_not_found",
            "raise_conflict",
            "raise_too_large",
            "raise_service_unavailable",
            "raise_internal_error",
            "raise_unauthorized",
            "raise_too_many_requests",
            "raise_gateway_timeout",
            "get_owned_or_404",
        )
        assert all(not hasattr(platform_pkg, name) for name in obsolete)

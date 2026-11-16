import pytest
from src.platform import (
    BaseAppException,
    ConflictError,
    DomainError,
    PreconditionFailedError,
    ResourceNotFoundError,
    ValidationFailedError,
)


class TestBaseAppException:
    def test_base_app_exception_has_error_id(self):
        "AC-platform.21.1"
        exc = BaseAppException(error_id="ERR_001", message="test error")
        assert exc.error_id == "ERR_001"

    def test_base_app_exception_has_status_code(self):
        "AC-platform.21.2"
        exc = BaseAppException(error_id="ERR_002", message="bad request", status_code=400)
        assert exc.status_code == 400

    def test_base_app_exception_is_subclass_of_exception(self):
        "AC-platform.21.3"
        exc = BaseAppException(error_id="ERR_003", message="error")
        assert isinstance(exc, Exception)
        "BaseAppException defaults to status_code=500 when not specified."
        exc = BaseAppException(error_id="ERR_003", message="error")
        assert exc.status_code == 500

    def test_base_app_exception_raise_and_catch(self):
        "AC-platform.21.4"
        with pytest.raises(BaseAppException) as exc_info:
            raise BaseAppException(error_id="ERR_004", message="raised!", status_code=422)
        assert exc_info.value.error_id == "ERR_004"
        assert exc_info.value.status_code == 422
        assert exc_info.value.message == "raised!"
        assert str(exc_info.value) == "raised!"

    async def test_base_app_exception_handler_returns_structured_json(self):
        "AC-platform.21.5"
        import json
        from unittest.mock import MagicMock
        from src.main import base_app_exception_handler

        mock_request = MagicMock()
        exc = BaseAppException(error_id="TEST_ERR", message="test message", status_code=422)
        response = await base_app_exception_handler(mock_request, exc)
        assert response.status_code == 422
        body = json.loads(response.body)
        assert body["error_id"] == "TEST_ERR"
        assert body["detail"] == "test message"

    @pytest.mark.parametrize(
        ("cls", "expected_status", "expected_error_id"),
        [
            (DomainError, 400, "bad_request"),
            (ValidationFailedError, 400, "bad_request"),
            (ResourceNotFoundError, 404, "not_found"),
            (ConflictError, 409, "conflict"),
            (PreconditionFailedError, 422, "unprocessable_entity"),
        ],
    )
    def test_domain_error_subclasses_bridge_value_error_and_base_app_exception(
        self, cls, expected_status, expected_error_id
    ):
        "AC-platform.21.5"
        exc = cls("domain rule failed")
        assert isinstance(exc, DomainError)
        assert isinstance(exc, BaseAppException)
        assert isinstance(exc, ValueError)
        assert str(exc) == "domain rule failed"
        assert exc.message == "domain rule failed"
        assert exc.status_code == expected_status
        assert exc.error_id == expected_error_id

"""Tests for exception utilities — AC12.21."""

import pytest

from src.utils.exceptions import BaseAppException


class TestBaseAppException:
    def test_base_app_exception_has_error_id(self):
        """AC12.21.1: BaseAppException stores the error_id attribute."""
        exc = BaseAppException(error_id="ERR_001", message="test error")
        assert exc.error_id == "ERR_001"

    def test_base_app_exception_has_status_code(self):
        """AC12.21.2: BaseAppException stores the status_code attribute."""
        exc = BaseAppException(error_id="ERR_002", message="bad request", status_code=400)
        assert exc.status_code == 400

    def test_base_app_exception_default_status_code(self):
        """AC12.21.3: BaseAppException defaults to status_code=500."""
        exc = BaseAppException(error_id="ERR_003", message="error")
        assert isinstance(exc, Exception)
        assert exc.status_code == 500

    def test_base_app_exception_raise_and_catch(self):
        """AC12.21.4: BaseAppException can be raised and caught."""
        with pytest.raises(BaseAppException) as exc_info:
            raise BaseAppException(error_id="ERR_004", message="raised!", status_code=422)
        assert exc_info.value.error_id == "ERR_004"
        assert exc_info.value.status_code == 422
        assert exc_info.value.message == "raised!"
        assert str(exc_info.value) == "raised!"

    @pytest.mark.asyncio
    async def test_base_app_exception_handler_returns_structured_json(self):
        """AC12.21.5: BaseAppException handler serializes error_id and status_code into JSON response."""
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
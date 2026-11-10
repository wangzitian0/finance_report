'AC-identity.1.3'; from __future__ import annotations; import pytest; from pydantic import ValidationError; from src.schemas.user import UserUpdate
class TestUserSchemas:
    def test_user_update_schema_optional_email(self) -> None:
        update = UserUpdate(); assert update.email is None; update = UserUpdate(email='new@example.com'); assert update.email == 'new@example.com'
        with pytest.raises(ValidationError): UserUpdate(email='not-an-email')

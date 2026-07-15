"""AC-identity.1.3: User schema validation unit tests (no database, no event loop).

Split out of test_users_router.py (#1767): that module carries a blanket
`pytestmark = pytest.mark.asyncio` for its router tests, which was incorrectly
also applying (and warning on) these synchronous schema-only tests -- a
module-level pytestmark cannot be overridden per-class, only avoided by
keeping sync tests out of an asyncio-marked module.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schemas.user import UserCreate, UserUpdate


class TestUserSchemas:
    """Unit tests for user schemas without database."""

    def test_user_create_schema_valid(self) -> None:
        user = UserCreate(email="test@example.com", password="securepassword123")
        assert user.email == "test@example.com"
        assert user.password == "securepassword123"

    def test_user_create_schema_invalid_email(self) -> None:
        with pytest.raises(ValidationError):
            UserCreate(email="not-an-email", password="securepassword123")

    def test_user_create_schema_short_password(self) -> None:
        with pytest.raises(ValidationError):
            UserCreate(email="test@example.com", password="short")

    def test_user_update_schema_optional_email(self) -> None:
        update = UserUpdate()
        assert update.email is None

        update = UserUpdate(email="new@example.com")
        assert update.email == "new@example.com"

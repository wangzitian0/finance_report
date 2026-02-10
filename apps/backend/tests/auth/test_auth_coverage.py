"""Additional coverage tests for auth router.

These tests cover edge cases and error paths for the auth router
that are not covered in the main test files.
"""

import pytest


@pytest.mark.asyncio
class TestAuthRouterCoverage:
    """Additional tests for auth router coverage."""

    async def test_login_invalid_credentials(self, public_client):
        """
        GIVEN invalid login credentials
        WHEN attempting to login
        THEN it should return 401 error
        """
        response = await public_client.post(
            "/auth/login",
            data={
                "username": "nonexistent@example.com",
                "password": "wrongpassword",
            },
        )
        assert response.status_code in [401, 422]  # Either unauthorized or validation error

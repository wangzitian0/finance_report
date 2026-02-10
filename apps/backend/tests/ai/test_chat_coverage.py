"""Additional coverage tests for chat router.

These tests cover edge cases and error paths for the chat router
that are not covered in the main test files.
"""

from uuid import uuid4

import pytest


@pytest.mark.asyncio
class TestChatRouterCoverage:
    """Additional tests for chat router coverage."""

    async def test_get_nonexistent_session(self, client):
        """
        GIVEN a non-existent session ID
        WHEN requesting session details
        THEN it should return 404
        """
        fake_id = uuid4()
        response = await client.get(f"/chat/sessions/{fake_id}")
        assert response.status_code == 404

    async def test_send_message_to_nonexistent_session(self, client):
        """
        GIVEN a non-existent session ID
        WHEN sending a message
        THEN it should return 404
        """
        fake_id = uuid4()
        response = await client.post(
            f"/chat/sessions/{fake_id}/messages",
            json={"content": "Hello"},
        )
        assert response.status_code == 404

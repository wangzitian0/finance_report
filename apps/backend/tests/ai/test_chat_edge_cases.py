from uuid import uuid4
class TestChatRouterCoverage:
    async def test_get_nonexistent_session(self, client): 'AC6.2.1'; fake_id = uuid4(); response = await client.get(f'/chat/sessions/{fake_id}'); assert response.status_code == 404
    async def test_send_message_to_nonexistent_session(self, client): 'AC6.2.2'; fake_id = uuid4(); response = await client.post(f'/chat/sessions/{fake_id}/messages', json={'content': 'Hello'}); assert response.status_code == 404

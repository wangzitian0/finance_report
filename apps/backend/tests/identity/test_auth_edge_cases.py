class TestAuthRouterCoverage:
    async def test_login_invalid_credentials(self, public_client): 'AC1.1.1'; response = await public_client.post('/auth/login', data={'username': 'nonexistent@example.com', 'password': 'wrongpassword'}); assert response.status_code in [401, 422]

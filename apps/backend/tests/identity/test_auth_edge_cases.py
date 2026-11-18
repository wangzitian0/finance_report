class TestAuthRouterCoverage:
    async def test_login_invalid_credentials(self, public_client):
        response = await public_client.post(
            "/auth/login", data={"username": "nonexistent@example.com", "password": "wrongpassword"}
        )
        assert response.status_code in [401, 422]


def test_password_and_jwt_token_lifecycle():
    from datetime import timedelta
    from src.identity import create_access_token, decode_access_token, hash_password, normalize_email, verify_password

    assert normalize_email("  User@Example.COM ") == "user@example.com"
    hashed = hash_password("S3cure!Pass")
    assert verify_password("S3cure!Pass", hashed)
    assert not verify_password("Wrong!Pass", hashed)
    token = create_access_token({"sub": "user789", "role": "admin"})
    payload = decode_access_token(token)
    assert payload is not None and payload["sub"] == "user789"
    expired = create_access_token({"sub": "expired"}, timedelta(seconds=-1))
    assert decode_access_token(expired) is None
    assert decode_access_token("not.a.valid.jwt.token") is None
    assert decode_access_token("") is None
    assert decode_access_token(None) is None

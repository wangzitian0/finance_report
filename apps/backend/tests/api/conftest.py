from __future__ import annotations

import pytest


class DummyStorage:
    def upload_bytes(self, *, key: str, content: bytes, content_type: str | None = None) -> None:
        return None

    def get_object(self, key: str) -> bytes:
        return b"dummy content"

    def generate_presigned_url(self, *, key: str, expires_in: int | None = None, public: bool = False) -> str:
        return f"https://example.com/{key}"

    def delete_object(self, key: str) -> None:
        return None


@pytest.fixture
def storage_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.routers.statements.StorageService", DummyStorage)

"""Pytest fixtures for API router tests."""

from __future__ import annotations

import pytest

from src.llm.base import Modality, ModelSpec
from src.routers import statements as statements_router


class DummyStorage:
    """Storage stub for statement upload tests."""

    def upload_bytes(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        return None

    def get_object(self, key: str) -> bytes:
        return b"dummy content"

    def generate_presigned_url(
        self,
        *,
        key: str,
        expires_in: int | None = None,
        public: bool = False,
    ) -> str:
        return f"https://example.com/{key}"

    def delete_object(self, key: str) -> None:
        return None


@pytest.fixture
def storage_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(statements_router, "StorageService", DummyStorage)


@pytest.fixture
def model_catalog_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_catalog_get(self, model_id):
        return ModelSpec(
            id=model_id,
            provider_id="env",
            modalities=frozenset({Modality.TEXT, Modality.IMAGE}),
        )

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)

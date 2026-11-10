from __future__ import annotations; import pytest; from src.config import settings
@pytest.fixture(autouse=True)
def pin_ai_key_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None: monkeypatch.setattr(settings, 'ai_api_key', '')

"""Shared fixtures for the AI advisor test package."""

from __future__ import annotations

import pytest

from src.config import settings


# --- Ambient AI-key isolation (#1804) ---
@pytest.fixture(autouse=True)
def pin_ai_key_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the env AI-provider key to "unconfigured" for every advisor test.

    ``settings.ai_api_key`` is read from two env vars (AI_API_KEY and
    ZAI_API_KEY, #2487). A developer machine that exports either of them silently flips
    ``EnvConfigSource.is_configured()`` to True, so tests asserting
    unconfigured-provider behaviour pass in CI (which exports none) but fail
    locally — the class of drift behind issue #1804. Pinning the key to ""
    makes every test in this package see the same deterministic surface as CI;
    tests that need a configured provider set ``service.api_key`` or patch
    ``get_config_source`` explicitly, which overrides this default.
    """
    # raising=True (default): if the field is ever renamed, fail loudly instead
    # of silently reverting this package to the ambient environment.
    monkeypatch.setattr(settings, "ai_api_key", "")

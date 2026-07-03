"""`resolve_env_tier` — mapping the runtime's ENVIRONMENT value to an `EnvTier` (AC-runtime.3.1, #1577).

The manifest speaks `EnvTier`; the running app knows `settings.environment`.
`resolve_env_tier` is the single translation between them, so `boot.validate`
can iterate `DEPENDENCY_MANIFEST.required_for(tier)`. Unknown values resolve to
PRODUCTION — the strictest tier — so a typo'd environment can only over-assert,
never under-assert (fail closed).
"""

from __future__ import annotations

import pytest

from src.runtime import EnvTier, resolve_env_tier

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ("development", EnvTier.LOCAL_DEV),
        ("test", EnvTier.LOCAL_CI),
        ("testing", EnvTier.LOCAL_CI),
        ("ci", EnvTier.LOCAL_CI),
        ("preview", EnvTier.PREVIEW),
        ("staging", EnvTier.STAGING),
        ("production", EnvTier.PRODUCTION),
    ],
)
def test_known_environments_resolve(environment: str, expected: EnvTier) -> None:
    assert resolve_env_tier(environment) is expected


def test_ci_environments_resolve_to_github_ci_on_github_actions() -> None:
    for environment in ("test", "testing", "ci"):
        assert resolve_env_tier(environment, github_actions=True) is EnvTier.GITHUB_CI


def test_resolution_is_case_and_whitespace_insensitive() -> None:
    assert resolve_env_tier("  Staging ") is EnvTier.STAGING


def test_unknown_environment_fails_closed_to_production() -> None:
    assert resolve_env_tier("qa-42") is EnvTier.PRODUCTION
    assert resolve_env_tier("") is EnvTier.PRODUCTION

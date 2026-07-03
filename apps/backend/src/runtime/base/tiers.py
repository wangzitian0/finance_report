"""`EnvTier` — the six environments a dependency can be declared for.

Mirrors `docs/ssot/environments.md#environment-overview` (the `six_environments`
SSOT). CI and Preview run light substitutes (Preview = same as CI but
persistent); Staging and Production run real backends. Local Dev / Local CI /
GitHub CI are the app-owned tiers (self-hosted via docker compose); Preview /
Staging / Production live on the VPS (implemented by infra2).
"""

from __future__ import annotations

from enum import Enum


class EnvTier(str, Enum):
    """One of the six environments."""

    LOCAL_DEV = "local_dev"
    LOCAL_CI = "local_ci"
    GITHUB_CI = "github_ci"
    PREVIEW = "preview"
    STAGING = "staging"
    PRODUCTION = "production"


#: The app-owned tiers — brought up in-place by the app itself (docker compose).
APP_OWNED_TIERS: frozenset[EnvTier] = frozenset({EnvTier.LOCAL_DEV, EnvTier.LOCAL_CI, EnvTier.GITHUB_CI})

#: The VPS tiers — provisioned by infra2.
VPS_TIERS: frozenset[EnvTier] = frozenset({EnvTier.PREVIEW, EnvTier.STAGING, EnvTier.PRODUCTION})


def resolve_env_tier(environment: str, *, github_actions: bool = False) -> EnvTier:
    """Map the runtime's ENVIRONMENT value to an `EnvTier` (#1577).

    The manifest speaks `EnvTier`; the running app knows `settings.environment`.
    This is the single translation between them. An unknown value resolves to
    PRODUCTION — the strictest tier — so a typo can only over-assert presence,
    never under-assert (fail closed).
    """
    normalized = environment.strip().lower()
    if normalized in {"development", "dev", "local"}:
        return EnvTier.LOCAL_DEV
    if normalized in {"test", "testing", "ci"}:
        return EnvTier.GITHUB_CI if github_actions else EnvTier.LOCAL_CI
    if normalized == "preview":
        return EnvTier.PREVIEW
    if normalized == "staging":
        return EnvTier.STAGING
    return EnvTier.PRODUCTION

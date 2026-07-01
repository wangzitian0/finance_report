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

"""`EnvTier` — the environments a dependency can be declared for.

Mirrors `common/runtime/environments.md#environment-overview` (the `environments`
SSOT) plus the infra2-provisioned Preview slot, which the app consumes but does
not own. CI and Preview run light substitutes (Preview = same as CI but
persistent); Staging and Production run real backends. Local Dev / Local CI /
GitHub CI are the app-owned tiers (self-hosted via podman compose); Preview /
Staging / Production live on the VPS (implemented by infra2).
"""

from __future__ import annotations

from enum import Enum

from infra2_sdk.runtime.environment import EnvironmentTier, resolve_environment_tier


class EnvTier(str, Enum):
    """One of the environments."""

    LOCAL_DEV = "local_dev"
    LOCAL_CI = "local_ci"
    GITHUB_CI = "github_ci"
    PREVIEW = "preview"
    STAGING = "staging"
    PRODUCTION = "production"


#: The app-owned tiers — brought up in-place by the app itself (podman compose).
APP_OWNED_TIERS: frozenset[EnvTier] = frozenset({EnvTier.LOCAL_DEV, EnvTier.LOCAL_CI, EnvTier.GITHUB_CI})

#: The VPS tiers — provisioned by infra2.
VPS_TIERS: frozenset[EnvTier] = frozenset({EnvTier.PREVIEW, EnvTier.STAGING, EnvTier.PRODUCTION})

_SDK_TIER_TO_ENV_TIER: dict[EnvironmentTier, EnvTier] = {
    EnvironmentTier.LOCAL_DEV: EnvTier.LOCAL_DEV,
    EnvironmentTier.LOCAL_TEST: EnvTier.LOCAL_CI,
    EnvironmentTier.GITHUB_CI: EnvTier.GITHUB_CI,
    EnvironmentTier.PREVIEW: EnvTier.PREVIEW,
    EnvironmentTier.STAGING: EnvTier.STAGING,
    EnvironmentTier.PRODUCTION: EnvTier.PRODUCTION,
}


def resolve_env_tier(environment: str, *, github_actions: bool = False) -> EnvTier:
    """Map the runtime's ENVIRONMENT value to an `EnvTier` (#1577, #2905).

    The manifest speaks `EnvTier`; the running app knows `settings.environment`.
    This is the single translation between them, delegating canonical alias and
    preview-slot recognition (`branch-*`, `pr-*`, `commit-*`, `tag-*`) to
    `infra2_sdk.runtime.environment.resolve_environment_tier`. An unknown value
    resolves to PRODUCTION — the strictest tier — so a typo can only over-assert
    presence, never under-assert (fail closed).
    """
    sdk_tier = resolve_environment_tier(
        environment,
        github_actions=github_actions,
        unknown="production",
    )
    return _SDK_TIER_TO_ENV_TIER[sdk_tier]

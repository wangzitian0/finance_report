"""Compat shim — the tier vocabulary moved to L0 (``common.meta.base``).

The authority-tier vocabulary + tier->proof matrix are part of the package
model itself ("one package = one tier"), so the machine source now lives in
:mod:`common.meta.base.authority_matrix` — the meta package (L0) may not
depend on this L1 package. ``authority`` keeps this import path alive for its
gates and the lightweight SSOT tooling; the module stays stdlib-only (the
re-export resolves through ``common.meta``'s lazy ``__getattr__``, which never
touches pydantic for these names).
"""

from __future__ import annotations

from common.meta.base.authority_matrix import (
    AC_PROOF_KINDS,
    AC_TIERS,
    ACProofKind,
    ACTier,
    PACKAGE_TIERS,
    PackageTier,
    TIER_DEFAULT_PROOF_KIND,
    TIER_VALID_PROOF_KINDS,
)

__all__ = [
    "AC_PROOF_KINDS",
    "AC_TIERS",
    "ACProofKind",
    "ACTier",
    "PACKAGE_TIERS",
    "PackageTier",
    "TIER_DEFAULT_PROOF_KIND",
    "TIER_VALID_PROOF_KINDS",
]

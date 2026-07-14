"""Compatibility re-export of the meta model (now in ``common.meta.base``).

The :class:`PackageContract` model moved into the meta package's ``base`` layer
(``common.meta.base.package_contract``) when the meta package adopted the
``base/extension/data`` layout it governs. This module is a thin, stable
re-export so existing imports — every ``common/<pkg>/contract.py`` and the
governance tests that do ``from common.meta.package_contract import ...`` — keep
working unchanged. Prefer importing from :mod:`common.meta.base.package_contract`
(or ``common.meta``) in new code.
"""

from __future__ import annotations

from common.meta.base.package_contract import (  # noqa: F401
    ACProofKind,
    ACRecord,
    ACStatus,
    ConceptRecord,
    Invariant,
    KIND_LAYER,
    Kind,
    Layer,
    PackageClass,
    PackageContract,
    PackageStatus,
    PackageTier,
    Priority,
    SPLIT,
    TIER_DEFAULT_PROOF_KIND,
    TIER_VALID_PROOF_KINDS,
    Unit,
)

__all__ = [
    "ACProofKind",
    "ACRecord",
    "ACStatus",
    "ConceptRecord",
    "Invariant",
    "KIND_LAYER",
    "Kind",
    "Layer",
    "PackageClass",
    "PackageContract",
    "PackageStatus",
    "PackageTier",
    "Priority",
    "SPLIT",
    "TIER_DEFAULT_PROOF_KIND",
    "TIER_VALID_PROOF_KINDS",
    "Unit",
]

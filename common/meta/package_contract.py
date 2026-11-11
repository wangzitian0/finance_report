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
    ac,
    acs,
    ConceptRecord,
    concepts,
    CommandBoundary,
    ContextRelation,
    ContextScope,
    GovernanceInitiative,
    GovernanceGuarantee,
    Invariant,
    invs,
    KIND_LAYER,
    Kind,
    Layer,
    PackageClass,
    PackageContract,
    PackageStatus,
    PackageTier,
    Priority,
    rels,
    SPLIT,
    suite,
    TIER_DEFAULT_PROOF_KIND,
    TIER_VALID_PROOF_KINDS,
    Unit,
    units,
)

__all__ = [
    "ACProofKind",
    "ACRecord",
    "ac",
    "acs",
    "ACStatus",
    "ConceptRecord",
    "concepts",
    "CommandBoundary",
    "ContextRelation",
    "ContextScope",
    "GovernanceInitiative",
    "GovernanceGuarantee",
    "Invariant",
    "invs",
    "KIND_LAYER",
    "Kind",
    "Layer",
    "PackageClass",
    "PackageContract",
    "PackageStatus",
    "PackageTier",
    "Priority",
    "rels",
    "SPLIT",
    "suite",
    "TIER_DEFAULT_PROOF_KIND",
    "TIER_VALID_PROOF_KINDS",
    "Unit",
    "units",
]

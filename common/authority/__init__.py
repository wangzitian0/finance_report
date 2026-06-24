"""``common.authority`` — the CODE↔LLM authority-tier bounded context.

One package owning the whole authority-tier concept (was scattered across
``common/ssot/``): the **value language** (the four-tier CODE↔LLM vocabulary +
the tier→proof matrix, ``authority_matrix``), the **detected view** (the
CODE/LLM band classifier, ``authority_classifier``), and the **enforcement**
(the gates: ``check_ac_proof_kind``, ``check_tier_ast_literal``,
``check_tier_imports``, ``check_ac_tier_baseline``, ``check_authority_reconcile``,
run via their ``tools/`` wrappers).

stdlib-only by design (no pydantic): importable by the lightweight CI lint env
and by ``common.governance``'s ``PackageContract`` model alike, so the declared
tier and the detected band share one vocabulary that cannot drift.
"""

from common.authority.authority_classifier import BANDS, band, classify_repo
from common.authority.authority_matrix import (
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
    "BANDS",
    "PACKAGE_TIERS",
    "PackageTier",
    "TIER_DEFAULT_PROOF_KIND",
    "TIER_VALID_PROOF_KINDS",
    "band",
    "classify_repo",
]

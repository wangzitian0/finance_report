"""The ``authority`` package's machine-checkable :class:`PackageContract`.

``authority`` is the CODE↔LLM authority-tier bounded context: the value language
(four-tier vocabulary + tier→proof matrix), the detected-band classifier, and the
gates that enforce the tier rules. It is a ``kernel`` leaf — depends on nothing
registered — and is itself governed by the very ``check_package_contract`` gate
its ``check_*`` siblings extend.
"""

from __future__ import annotations

from common.governance.package_contract import Invariant, PackageContract

CONTRACT = PackageContract(
    name="authority",
    klass="kernel",
    status="active",
    # The package defines the tier vocabulary; it is pure deterministic code
    # (AST/text, no LLM): CODE-ONLY.
    tier="CODE-ONLY",
    depends_on=[],
    roles=["matrix", "classifier", "gates"],
    implementations={"be": "common/authority", "fe": None},
    interface=[
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
    ],
    events=[],
    invariants=[
        Invariant(
            id="one-vocabulary-two-views",
            statement=(
                "The detected band scale (authority_classifier.BANDS) IS the "
                "declared tier scale (authority_matrix.PACKAGE_TIERS) — one "
                "vocabulary for both views, so they cannot drift."
            ),
            test=(
                "tests/tooling/test_authority_classifier.py"
                "::test_AC26_9_1_band_boundaries"
            ),
        ),
        Invariant(
            id="declared-reconciles-with-detected",
            statement=(
                "A shipped package's declared tier agrees with its detected "
                "CODE/LLM band at the enforceable ends (CODE-ONLY ⟹ no LLM test; "
                "LLM-ONLY ⟹ no deterministic test)."
            ),
            test=(
                "tests/tooling/test_migration_safety_gates.py"
                "::test_reconcile_flags_llm_test_under_code_only"
            ),
        ),
    ],
    roadmap=[],
)

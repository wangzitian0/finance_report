"""The ``authority`` package's machine-checkable :class:`PackageContract`.

``authority`` is the CODE↔LLM authority-tier bounded context: the value language
(four-tier vocabulary + tier→proof matrix), the detected-band classifier, and the
gates that enforce the tier rules. It is a ``kernel`` leaf — depends on nothing
registered — and is itself governed by the very ``check_package_contract`` gate
its ``check_*`` siblings extend.
"""

from __future__ import annotations

from common.governance.package_contract import ACRecord, Invariant, PackageContract

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
    # The authority-tier-SYSTEM ACs (EPIC-026 phases 1-3), homed here from the EPIC
    # table. They KEEP their numeric ids (AC26.x): renumbering to AC-authority.*
    # would orphan the cross-references EPIC-008 makes to them and the test refs —
    # the AC-<pkg> scheme is for net-new ACs, not for re-homing cross-referenced
    # ones. They inherit the package's CODE-ONLY tier.
    # NOT homed: AC26.8.1 (financial-invariant observability — extraction domain)
    # and AC26.9.1 (the CODE/LLM classifier — its proof test is marker-laden, so
    # the reconcile gate would read authority as CODE-LED); both stay in EPIC-026.
    roadmap=[
        ACRecord(
            id="AC26.1.1",
            statement=(
                "authority-tiers.md is the single registered owner of the tier "
                "vocabulary, the cross-tier MUST rules, and the tier->proof matrix."
            ),
            test=(
                "tests/tooling/test_ac_authority_tiers.py"
                "::test_AC26_1_1_ssot_defines_five_tiers_and_proof_matrix"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC26.2.1",
            statement=(
                "A {tier:XX} marker at an AC's definition site flows tier into its "
                "registry value (stripped from the description); an undeclared or "
                "invalid code is ignored, not an error."
            ),
            test=(
                "tests/tooling/test_ac_authority_tiers.py"
                "::test_AC26_2_1_tier_marker_flows_into_registry_value"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC26.3.1",
            statement=(
                "The tier ratchet is shrink-only: a new/changed AC absent from the "
                "untagged-debt baseline must declare a tier, and --update never "
                "launders fresh untagged debt."
            ),
            test=(
                "tests/tooling/test_ac_authority_tiers.py"
                "::test_AC26_3_1_tier_ratchet_is_shrink_only_and_blocks_new_debt"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC26.4.1",
            statement=(
                "The first-batch EPICs (003/006/021/023) are fully tier-tagged and "
                "off the untagged-debt baseline."
            ),
            test=(
                "tests/tooling/test_ac_authority_tiers.py"
                "::test_AC26_4_1_first_batch_epics_fully_tagged_and_off_baseline"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC26.5.1",
            statement=(
                "A {proof:KIND} marker flows into the registry as proof_kind "
                "(defaulting to the tier's canonical kind); the gate enforces the "
                "tier->proof matrix for tier-tagged ACs (LLM-LED/LLM-ONLY never "
                "exact, HU is evidence)."
            ),
            test=(
                "tests/tooling/test_ac_proof_kind.py"
                "::test_AC26_5_1_proof_kind_marker_flows_and_gate_enforces_matrix"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC26.6.1",
            statement=(
                "The first-batch LLM-LED/HU/LLM-ONLY ACs each declare a matrix-valid "
                "proof_kind; the LLM-LED ones carry invariant/property proofs (the "
                "balance-chain + #1254 dedup-conservation properties)."
            ),
            test=(
                "tests/tooling/test_ac_proof_kind.py"
                "::test_AC26_6_1_first_batch_lp_acs_carry_invariant_proof"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC26.7.1",
            statement=(
                "CODE-ONLY / financial-truth modules are statically proven free of "
                "LLM-layer imports (check_tier_imports, AST, direct-imports-only); "
                "a glob that resolves to no file also fails so the set can't shrink."
            ),
            test=(
                "tests/tooling/test_tier_imports.py"
                "::test_AC26_7_1_real_tree_has_no_llm_imports_in_protected_modules"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
    ],
)

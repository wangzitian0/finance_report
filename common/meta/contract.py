"""The ``meta`` package's own :class:`PackageContract`.

The package model self-hosts: the meta package that *defines* what a package is
(``PackageContract`` / ``ACRecord`` / ``Invariant`` / ``Unit`` / ``Kind`` and the
``check_package_contract`` gate) is itself a package, with a ``readme.md`` (the
package-model spec), this ``contract.py``, and a ``todo.md``. It is discovered
and validated by the very gate it ships, so the model proves itself.

meta is also the Layout-3 exemplar: it converges into the ``base`` / ``extension``
/ ``data`` layers it governs, and declares its DDD building-block ``units`` (the
``PackageContract`` aggregate root + its value objects in ``base``, the gate as a
``domain-service`` in ``extension``, and ``contract_index`` as a ``projection`` in
``data``). Its BE implementation is ``common/meta`` (the same directory): the
published language is ``common/meta/__init__.py``'s ``__all__``.
"""

from __future__ import annotations

from common.meta.package_contract import (
    ACRecord,
    Invariant,
    Kind,
    PackageContract,
    Unit,
)

CONTRACT = PackageContract(
    name="meta",
    status="active",
    # The package-model gate is deterministic code (AST + set comparison), no
    # LLM: a pure-code (CODE-ONLY) package. It also OWNS the authority-tier rules below.
    tier="CODE-ONLY",
    # L0 depends on nothing: the tier vocabulary (base/authority_matrix.py) and
    # the five-layer topology (base/layering.py) are meta's own base modules.
    depends_on=[],
    roles=["base", "extension", "data"],
    units=[
        # base — the pure model: the PackageContract aggregate root + its value
        # objects, and the building-block taxonomy. All live in base/package_contract.py.
        Unit(
            name="PackageContract",
            kind=Kind.AGGREGATE_ROOT,
            module="base/package_contract.py",
        ),
        Unit(
            name="ACRecord", kind=Kind.VALUE_OBJECT, module="base/package_contract.py"
        ),
        Unit(
            name="Invariant", kind=Kind.VALUE_OBJECT, module="base/package_contract.py"
        ),
        Unit(name="Unit", kind=Kind.VALUE_OBJECT, module="base/package_contract.py"),
        Unit(name="Kind", kind=Kind.VALUE_OBJECT, module="base/package_contract.py"),
        # extension — the impure edge: the governance gate (a domain service that
        # walks the tree and validates every package against its contract).
        Unit(
            name="check_package_contract",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/check_package_contract.py",
        ),
        # data — the read-model: the computed meta-index over all contracts.
        Unit(name="contract_index", kind=Kind.PROJECTION, module="data/projection.py"),
    ],
    implementations={"be": "common/meta", "fe": None},
    interface=[
        "ACRecord",
        "Invariant",
        "Kind",
        "PackageContract",
        "Unit",
        "contract_index",
    ],
    events=[],
    invariants=[
        Invariant(
            id="contract-equals-published-language",
            statement=(
                "A package's contract.interface must equal its BE implementation's "
                "__init__.__all__; a drift between the declared and published "
                "language is reported by the gate."
            ),
            test=(
                "tests/tooling/test_check_package_contract.py"
                "::test_interface_mismatch_is_reported"
            ),
        ),
        Invariant(
            id="unproven-reference-is-rejected",
            statement=(
                "Every invariants[].test and roadmap[].test must resolve to a real "
                "test function; an unresolved reference is a gate failure."
            ),
            test=(
                "tests/tooling/test_check_package_contract.py"
                "::test_unresolved_invariant_and_roadmap_refs_are_reported"
            ),
        ),
        Invariant(
            id="dag-down-only",
            statement=(
                "A package's implementation may import only strictly-lower-class "
                "packages declared in depends_on; an upward/sideways/undeclared "
                "edge is rejected (the project stays a DAG)."
            ),
            test=(
                "tests/tooling/test_check_package_contract.py"
                "::test_upward_edge_is_forbidden"
            ),
        ),
        Invariant(
            id="active-package-has-a-decided-tier",
            statement=(
                "Authority tier is a module-design property declared once on the "
                "PackageContract (common/authority/readme.md). An active/"
                "deprecated package must have resolved its tier to one of "
                "CODE-ONLY/CODE-LED/LLM-LED/LLM-ONLY; only a draft package may leave tier undecided (the "
                "legacy 'HU' state), so a shipped untyped package is "
                "unrepresentable."
            ),
            test=(
                "tests/tooling/test_check_package_contract.py"
                "::test_active_package_must_declare_a_tier"
            ),
        ),
        Invariant(
            id="ac-proof-kind-satisfies-package-tier-matrix",
            statement=(
                "Every roadmap AC's proof_kind must be valid for the package's "
                "tier per the single machine matrix "
                "(package_contract.TIER_VALID_PROOF_KINDS); PackageContract "
                "enforces it at construction, so a contract that violates the "
                "tier->proof matrix (e.g. an LLM-LED/LLM-ONLY package with an AC claiming an "
                "exact golden proof) fails to import."
            ),
            test=(
                "tests/tooling/test_check_package_contract.py"
                "::test_package_proof_kind_must_satisfy_the_tier_matrix"
            ),
        ),
        # Structural guarantees about meta ITSELF as the Layout-3 exemplar (no
        # authority tier, not matrix-constrained — see common/authority/readme.md).
        Invariant(
            id="meta-converges-by-layer",
            statement=(
                "The meta package converges into base/ (the pure model) + "
                "extension/ (the gate) + data/ (the projection) — the layout it "
                "governs."
            ),
            test=("tests/tooling/test_meta_layering.py::test_meta_converges_by_layer"),
        ),
        Invariant(
            id="meta-base-is-pure",
            statement=(
                "The meta base/ layer never imports its own extension/ or data/ — "
                "the model is the pure, downward-only core."
            ),
            test="tests/tooling/test_meta_layering.py::test_meta_base_is_pure",
        ),
        Invariant(
            id="every-common-directory-is-governed-or-excepted",
            statement=(
                "check_package_contract discovers packages additively (globs "
                "common/*/contract.py), so a directory with no contract.py is "
                "invisible to it -- how common/ci, common/shell, and common/ssot "
                "accumulated as undeclared junk drawers (#1564-#1568). "
                "check_package_directory_coverage closes that gap from the other "
                "direction: every directory directly under common/ must ship a "
                "contract.py or be a documented, reasoned entry in "
                "UNGOVERNED_EXCEPTIONS, so a new junk drawer cannot silently "
                "recur."
            ),
            test=(
                "tests/tooling/test_check_package_directory_coverage.py"
                "::test_bare_directory_with_no_exception_is_rejected"
            ),
        ),
        # ── authority-tier vocabulary + gates folded in (was the `authority` package) ──
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
    roadmap=[
        # The governance gate's building-block behavior — meta's domain. Each AC
        # is proven by a negative test driving the gate against a synthetic
        # package that violates the rule.
        ACRecord(
            id="AC-meta.kind.1",
            statement=(
                "A declared unit must live in the layer its kind dictates "
                "(KIND_LAYER); a unit whose module sits in the wrong layer is "
                "rejected (mechanism A)."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_kind_1_unit_misplacement_is_rejected"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.kind.2",
            statement=(
                "A repository unit must split into a base port + an extension "
                "adapter; a port outside base/ or an adapter outside extension/ is "
                "rejected (mechanism B, dependency inversion)."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_kind_2_repository_requires_port_and_adapter"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.kind.3",
            statement=(
                "The data/ layer is a sink: nothing in base/ or extension/ may "
                "import the package's own data/, so the read-model never feeds back "
                "into the write side."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_kind_3_data_layer_is_a_sink"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.projection.1",
            statement=(
                "contract_index is a pure projection over the contracts it is "
                "handed: registry, AC index, reverse-dependency consumers, and "
                "per-package units-by-layer, with no I/O of its own."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_projection_1_contract_index_is_pure"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.kind.4",
            statement=(
                "A value-type package may declare value-object units for the "
                "taxonomy without the physical base/extension split; the gate "
                "accepts it (additive) and still passes."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_kind_4_value_type_packages_pass"
            ),
            priority="P2",
            status="done",
        ),
        # One-transaction-per-domain (issue #1460, Decision B made executable):
        # one DB transaction belongs to exactly one domain; cross-domain changes
        # go through a published interface or an id + a domain event — never a
        # shared cross-domain transaction or a cross-domain FK. AC-meta.event.1
        # (outbox atomicity) is a runtime property left to the platform package's
        # own tests, not this structural gate, so it is intentionally not listed.
        ACRecord(
            id="AC-meta.txn.1",
            statement=(
                "A base unit reaching into another registered domain's unpublished "
                "object (an internal entity/aggregate, not a symbol in that "
                "package's __all__) is rejected; a cross-domain reference goes "
                "through the published interface (root import or a published "
                "symbol) or by id."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_txn_1_base_deep_import_of_other_domain_object_is_rejected"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.txn.2",
            statement=(
                "A domain's extension reaching into another domain's ORM/models (an "
                "unpublished internal) is rejected: a cross-domain effect must be a "
                "published domain event, not another domain's tables written in the "
                "same transaction. A plain deep 'import src.<other>.<sub>' is "
                "rejected too (it names no published symbol)."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_txn_2_extension_writing_other_domain_orm_is_rejected"
            ),
            priority="P0",
            status="done",
        ),
        # The five-layer topology (meta < infra < middleware < domain < app):
        # placement is global topology owned by L0 as the central PACKAGE_LAYER
        # map (base/layering.py) — packages do not self-claim a klass.
        ACRecord(
            id="AC-meta.layer.1",
            statement=(
                "The package topology is the five ordered layers meta < infra < "
                "middleware < domain < app (LAYER_RANK); the retired "
                "kernel/platform/core vocabulary no longer constructs a contract."
            ),
            test=(
                "tests/tooling/test_five_layer_model.py"
                "::test_old_klass_vocabulary_is_rejected"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.layer.2",
            statement=(
                "Placement is resolved from the central PACKAGE_LAYER map: a "
                "mapped package needs no declared klass, a declaration that "
                "contradicts the map is rejected, and an unmapped package "
                "without a declaration is unplaceable."
            ),
            test=(
                "tests/tooling/test_five_layer_model.py"
                "::test_declared_klass_must_match_central_map"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.layer.3",
            statement=(
                "No declared depends_on edge points to a higher layer — in "
                "particular meta (L0) depends on nothing: the tier vocabulary "
                "and the topology are its own base modules."
            ),
            test=(
                "tests/tooling/test_five_layer_model.py"
                "::test_no_depends_on_edge_points_to_a_higher_layer"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.layer.4",
            statement=(
                "The L0 vocabulary modules (base/layering.py, "
                "base/authority_matrix.py) stay importable without pydantic, "
                "preserving the lightweight CI lint env guarantee."
            ),
            test=(
                "tests/tooling/test_five_layer_model.py"
                "::test_layer_vocabulary_imports_without_pydantic"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.layer.5",
            statement=(
                "common/meta/readme.md carries the authoritative mermaid "
                "five-layer diagram naming all five layers."
            ),
            test=(
                "tests/tooling/test_five_layer_model.py"
                "::test_readme_carries_the_mermaid_five_layer_diagram"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.txn.3",
            statement=(
                "A SQLAlchemy ForeignKey/relationship whose target table or model "
                "belongs to another registered domain is rejected; a cross-domain "
                "reference must be an id column resolved via the interface/event, "
                "not a database FK. Detection is AST-only/best-effort on the "
                "string-target forms (documented in the gate)."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_txn_3_cross_domain_fk_is_rejected"
            ),
            priority="P1",
            status="done",
        ),
        # The taxonomy migrated in place, so its retired vocabulary lingers in
        # prose; the drift gate makes "old words presented as current" a CI
        # failure instead of a periodic manual audit.
        ACRecord(
            id="AC-meta.vocab.1",
            statement=(
                "Retired taxonomy vocabulary (klass kernel/platform/core, "
                "types/ops/store/api roles, asset_evaluation) presented as "
                "current truth in docs/SSOT/EPIC/test prose fails the "
                "taxonomy-drift gate; a mention passes only with a nearby "
                "historical marker (formerly/replaces/retired/...)."
            ),
            test=(
                "tests/tooling/test_taxonomy_drift.py"
                "::test_AC_meta_vocab_1_repo_is_clean"
            ),
            priority="P1",
            status="done",
        ),
        # ── authority-tier SYSTEM ACs (EPIC-026), folded from the `authority` package ──
        ACRecord(
            id="AC-authority.1.1",
            statement=(
                "common/authority/readme.md is the single registered owner of the "
                "tier vocabulary, the cross-tier MUST rules, and the tier->proof "
                "matrix (internalized from the retired docs/ssot/authority-tiers.md)."
            ),
            test=(
                "tests/tooling/test_ac_authority_tiers.py"
                "::test_AC26_1_1_ssot_defines_five_tiers_and_proof_matrix"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-authority.2.1",
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
            id="AC-authority.3.1",
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
            id="AC-authority.4.1",
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
            id="AC-authority.5.1",
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
            id="AC-authority.6.1",
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
            id="AC-authority.7.1",
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

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
``data``). The pure dependency graph policy lives in ``base``; ``data`` exposes
its computed projection and ``extension`` renders ref-isolated impact reports.
Its BE implementation is ``common/meta`` (the same directory): the published
language is ``common/meta/__init__.py``'s ``__all__``.
"""

from __future__ import annotations

from common.meta.package_contract import (
    ACRecord,
    ConceptRecord,
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
        Unit(
            name="DependencyKind",
            kind=Kind.VALUE_OBJECT,
            module="base/dependency_graph.py",
        ),
        Unit(
            name="DependencyEdge",
            kind=Kind.VALUE_OBJECT,
            module="base/dependency_graph.py",
        ),
        # extension — the impure edge: the governance gate (a domain service that
        # walks the tree and validates every package against its contract).
        Unit(
            name="check_package_contract",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/check_package_contract.py",
        ),
        Unit(
            name="dependency_report",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/dependency_report.py",
        ),
        # data — the read-model: the computed meta-index over all contracts.
        Unit(name="contract_index", kind=Kind.PROJECTION, module="data/projection.py"),
        Unit(name="ac_vision_index", kind=Kind.PROJECTION, module="data/projection.py"),
        Unit(
            name="dependency_index", kind=Kind.PROJECTION, module="data/projection.py"
        ),
    ],
    implementations={"be": "common/meta", "fe": None},
    interface=[
        "ACRecord",
        "ConceptRecord",
        "DependencyEdge",
        "DependencyKind",
        "Invariant",
        "Kind",
        "PackageContract",
        "Unit",
        "ac_vision_index",
        "concept_index",
        "contract_index",
        "dependency_index",
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
            id="public-function-has-single-package-owner",
            statement=(
                "A snake_case public function name may be exported by exactly one "
                "package contract; duplicate exports are rejected so package "
                "ownership cannot silently diverge."
            ),
            test=(
                "tests/tooling/test_check_package_contract.py"
                "::test_duplicate_public_function_exports_are_rejected"
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
                "PackageContract (common/meta/readme.md). An active/"
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
        # authority tier, not matrix-constrained — see common/meta/readme.md).
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
                "common/*/contract.py for a module-level "
                "CONTRACT = PackageContract(...)), so a directory with no "
                "discoverable contract is invisible to it -- how common/ci, "
                "common/shell, and common/ssot accumulated as undeclared junk "
                "drawers (#1564-#1568). "
                "check_package_directory_coverage closes that gap from the other "
                "direction: every directory directly under common/ must ship a "
                "contract.py with a module-level "
                "CONTRACT = PackageContract(...) or be a documented, reasoned "
                "entry in UNGOVERNED_EXCEPTIONS, so a missing, lowercase, "
                "wrong-type, or unloadable declaration cannot silently recur."
            ),
            test=(
                "tests/tooling/test_check_package_directory_coverage.py"
                "::test_contract_file_without_exported_contract_is_rejected"
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
            id="AC-meta.dependency-governance.1",
            statement=(
                "The computed dependency index projects package contracts into "
                "typed edges plus deterministic direct and transitive consumers, "
                "and rejects duplicate, unknown, self, or cyclic package topology."
            ),
            test=(
                "tests/tooling/test_ddd_dependency_report.py"
                "::test_AC_meta_dependency_governance_1_projection_has_typed_edges_and_transitive_consumers"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.dependency-governance.2",
            statement=(
                "A ref-isolated base-vs-HEAD dependency impact report shows typed "
                "edge and public-boundary changes with every direct and transitive "
                "consumer. Boundary fingerprints resolve root bindings, local "
                "aliases, inherited APIs, and named defaults without importing "
                "implementation modules; unreadable discovery or ambiguous exports "
                "fail closed."
            ),
            test=(
                "tests/tooling/test_ddd_dependency_report.py"
                "::test_AC_meta_dependency_governance_2_impact_includes_indirect_consumers"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.vision-anchor.1",
            statement=(
                "A package-roadmap AC may declare one vision.md anchor, and "
                "ac_vision_index purely projects every declared AC id to that "
                "anchor without assigning anchor ownership centrally."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_vision_anchor_1_projection_is_pure"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.vision-anchor.2",
            statement=(
                "The vision proof matrix includes package-roadmap ACs under "
                "their declared vision anchors and rejects any anchor absent "
                "from vision.md."
            ),
            test=(
                "tests/tooling/test_generate_vision_proof_matrix.py"
                "::test_AC_meta_vision_anchor_2_package_ac_backs_vision_node"
            ),
            priority="P0",
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
                "A SQLAlchemy relationship(...) whose target model belongs to "
                "another registered domain is rejected; a cross-domain reference "
                "must resolve the id via the interface/event, never navigate an "
                "ORM object graph. A bare cross-domain ForeignKey column (no "
                "relationship) is allowed — a DB-level referential-integrity "
                "invariant, not code-level coupling (#1675). Detection is "
                "AST-only/best-effort on the string-target forms (documented in "
                "the gate)."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_txn_3_cross_domain_relationship_is_rejected_fk_column_is_allowed"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.txn.4",
            statement=(
                "A DB-level ondelete=CASCADE is a hidden write below the "
                "application — one table's delete silently mutating other "
                "rows; across domains it breaks one-txn-per-domain and "
                "append-only domains, the risk this ratchet exists for. The "
                'census of ForeignKey(..., ondelete="CASCADE") target tables '
                "under apps/backend/src (all sites — deliberately not "
                "domain-aware until models decentralization, #1675 D5/D6, "
                "makes table ownership derivable) must equal "
                "common/meta/data/fk-cascade-baseline.json: silent growth fails CI; "
                "adding a cascade requires raising the baseline in the same "
                "PR, where the diff makes the choice reviewable (the "
                "app-boundary idiom); removals prune the baseline in the same "
                "PR. Existing sites are grandfathered; the end-state is "
                "saga-owned deletion (#1675 ruling, D1/D7)."
            ),
            test=(
                "tests/tooling/test_fk_cascade_ratchet.py"
                "::test_AC_meta_txn_4_cross_domain_cascade_only_shrinks"
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
                "common/meta/readme.md is the single registered owner of the "
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
        ACRecord(
            id="AC-meta.router.1",
            statement=(
                "No backend router module imports a symbol from another "
                "router (`from src.routers.<x> import ...` is absent across "
                "apps/backend/src/routers, excluding the package "
                "aggregator's legitimate `from src.routers import ...`); "
                "router-to-router coupling that hides the real logic owner "
                "is rejected. Was EPIC-025 AC25.5.1."
            ),
            test=(
                "apps/backend/tests/api/test_router_boundary.py"
                "::test_AC25_5_1_no_router_imports_another_router"
            ),
            priority="P1",
            status="done",
        ),
        # ── migrated from EPIC-014 (TTD transformation), migration closeout
        # wave 2 (#1663): foundational dev-tooling gates. Was AC14.1.1-.5. ──
        ACRecord(
            id="AC-meta.foundation-tooling.1",
            statement="Backend coverage threshold is enforced locally via apps/backend/pyproject.toml's --cov-fail-under. Was AC14.1.1.",
            test="tests/tooling/test_issue_493_foundation_ttd_behavior.py::test_AC14_1_1_backend_pyproject_enforces_local_coverage_threshold",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.foundation-tooling.2",
            statement="The pre-commit mypy hook runs against apps/backend/src and blocks type errors before commit. Was AC14.1.2.",
            test="tests/tooling/test_issue_493_foundation_ttd_behavior.py::test_AC14_1_2_pre_commit_mypy_hook_blocks_backend_type_errors",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.foundation-tooling.3",
            statement="validate_schemas.py exits non-zero when a Pydantic Field() lacks a description. Was AC14.1.3.",
            test="tests/tooling/test_issue_493_foundation_ttd_behavior.py::test_AC14_1_3_validate_schemas_exits_nonzero_for_missing_field_descriptions",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.foundation-tooling.4",
            statement="check_env_keys.py exits non-zero on config/.env.example drift. Was AC14.1.4.",
            test="tests/tooling/test_issue_493_foundation_ttd_behavior.py::test_AC14_1_4_check_env_keys_exits_nonzero_for_config_documentation_drift",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.foundation-tooling.5",
            statement="smoke_test.sh succeeds against a mocked local environment (health, pages, auth, CORS all pass). Was AC14.1.5.",
            test="tests/tooling/test_issue_493_foundation_ttd_behavior.py::test_AC14_1_5_smoke_test_succeeds_against_mocked_local_environment",
            priority="P1",
            status="done",
        ),
        # ── migrated from EPIC-014, wave 2 (#1663): AC-registry generation
        # itself. Was AC14.1.6. ──
        ACRecord(
            id="AC-meta.registry.1",
            statement="generate_ac_registry.py produces zero ghost ACs (reference-only mentions never create an entry) and zero id overlap between the feature and infra registries. Was AC14.1.6.",
            test="tests/tooling/test_issue_493_foundation_ttd_behavior.py::test_AC14_1_6_generate_ac_registry_check_rejects_ghosts_and_keeps_no_overlap",
            priority="P1",
            status="done",
        ),
        # ── migrated from EPIC-014, wave 2 (#1663): doc-consistency lint
        # rules. Was AC14.1.7/.8/.10. ──
        ACRecord(
            id="AC-meta.doc-consistency.1",
            statement="Generated analysis snapshots are not checked into docs/project/; live coverage and mismatch data come from tools or CI artifacts, not committed prose. Was AC14.1.7.",
            test="tests/tooling/test_lint_doc_consistency.py::test_AC14_1_7_generated_analysis_snapshots_are_absent",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.doc-consistency.2",
            statement="Reconciliation threshold prose points to its code/config owner instead of claiming the Markdown copy is the single authority. Was AC14.1.8.",
            test="tests/tooling/test_lint_doc_consistency.py::test_AC14_1_8_reconciliation_thresholds_are_code_owned",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.doc-consistency.3",
            statement="Frontend source cannot call raw fetch() outside apps/frontend/src/lib/api.ts. Was AC14.1.10.",
            test="tests/tooling/test_lint_doc_consistency.py::test_AC14_1_10_frontend_raw_fetch_is_limited_to_api_wrapper",
            priority="P0",
            status="done",
        ),
        # ── migrated from EPIC-014, wave 2 (#1663): the SSOT HLS governance
        # loop (manifest anchors, governance report/gates/ratchets, family
        # model, threshold-cleanup proof binding). Was AC14.1.9/.12-.16/.18/.23. ──
        ACRecord(
            id="AC-meta.ssot-governance.1",
            statement="SSOT manifest #anchor owners and cross-references resolve to actual Markdown anchors. Was AC14.1.9.",
            test="tests/tooling/test_check_manifest.py::test_AC14_1_9_manifest_anchor_refs_must_exist",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.ssot-governance.2",
            statement="SSOT governance metrics report Finance Report manifest shape, proof coverage, and future gate candidates without blocking CI. Was AC14.1.12.",
            test="tests/tooling/test_ssot_governance_report.py::test_AC14_1_12_report_covers_finance_manifest_shape",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.ssot-governance.3",
            statement="SSOT governance gates block changed-file and changed-manifest-entry debt, explain #823/HLS ownership, and support issue-linked temporary exceptions. Was AC14.1.13.",
            test="tests/tooling/test_ssot_governance_report.py::test_AC14_1_13_incremental_gate_only_blocks_changed_ssot_debt",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.ssot-governance.4",
            statement="Threshold cleanup for #824 reduces finance_report.orphan_ssot_files to zero by binding orphan SSOT files to parent concepts, without runtime behavior changes. Was AC14.1.14.",
            test="tests/tooling/test_ssot_governance_report.py::test_AC14_1_14_finance_report_orphan_ssot_files_are_manifest_owned",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.ssot-governance.5",
            statement="Threshold cleanup for #824 migrates representative machine-owned FR SSOT entries to explicit family/kind/proofs and inbound links so machine_owner_entries_missing_proof stays zero. Was AC14.1.15.",
            test="tests/tooling/test_ssot_governance_report.py::test_AC14_1_15_machine_owned_ssot_entries_have_explicit_shape_and_proof",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.ssot-governance.6",
            statement="SSOT governance gates keep protected per-system governance ratios non-decreasing and protected debt counts non-increasing against the base ref. Was AC14.1.16.",
            test="tests/tooling/test_ssot_governance_report.py::test_AC14_1_16_ssot_governance_ratios_cannot_regress",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.ssot-governance.7",
            statement="FR (EPIC-014) and infra2 (Infra-006) each document a 6-8 family SSOT HLS model with explicit concept/clause boundaries covering every MANIFEST.yaml-inferred family, linking #821/#822/#823/#824, and the definition does not move or re-own any SSOT concept. Was AC14.1.18.",
            test="tests/tooling/test_ssot_hls_family_model.py::test_AC14_1_18_fr_hls_family_model_is_documented_and_consistent",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.ssot-governance.8",
            statement="Threshold cleanup for #824 reduces finance_report.high_risk_entries_missing_proof to zero by binding the flagged high-risk platform concepts to existing proof tests, without runtime behavior changes. Was AC14.1.23.",
            test="tests/tooling/test_ssot_governance_report.py::test_AC14_1_23_high_risk_ssot_entries_bind_proof_under_platform_family",
            priority="P1",
            status="done",
        ),
        # ── migrated from EPIC-014, wave 2 (#1663): GitHub issue template
        # contract. Was AC14.1.11. ──
        ACRecord(
            id="AC-meta.issue-templates.1",
            statement="GitHub issue templates require phenomenon, reproduction, minimal-fix, and rationale/acceptance-criteria sections with valid repository labels. Was AC14.1.11.",
            test="tests/tooling/test_issue_template_contract.py::test_AC14_1_11_issue_templates_carry_their_type_required_fields",
            priority="P1",
            status="done",
        ),
        # ── migrated from EPIC-014, wave 2 (#1663): mechanically-generated
        # reference docs (DB schema, vision-proof matrix, EPIC status). Was
        # AC14.1.17/.19/.22. ──
        ACRecord(
            id="AC-meta.generated-refs.1",
            statement="The DB schema inventory is generated from SQLAlchemy metadata, CI-checked for deterministic generation, and linked from macro SSOT/domain docs instead of hand-maintained. Was AC14.1.17.",
            test="tests/tooling/test_generate_db_schema_reference.py::test_AC14_1_17_render_db_schema_reference_uses_sqlalchemy_metadata",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.generated-refs.2",
            statement="A single parseable vision-to-proof matrix is mechanically generated from vision.md anchors, EPIC ownership declarations, package-roadmap vision_anchor declarations, the AC registries, and test references, and --check fails on drift. Was AC14.1.19.",
            test="tests/tooling/test_generate_vision_proof_matrix.py::test_AC14_1_19_matrix_maps_vision_to_ac_to_test",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.generated-refs.3",
            statement="README EPIC status/completion is generated from the AC registries and test reports (not hand-written), reports coverage/placeholder/manual-gate/blocker categories separately, and is guarded by a generate-with--check drift gate. Was AC14.1.22.",
            test="tests/tooling/test_generate_epic_status.py::test_AC14_1_22_check_fails_on_drift",
            priority="P1",
            status="done",
        ),
        # ── migrated from EPIC-014, wave 2 (#1663): unified-coverage artifact
        # preflight + component tiers (#414/#923). Was AC14.1.20/.21. ──
        ACRecord(
            id="AC-meta.coverage-tiers.1",
            statement="Unified coverage aggregation runs an artifact preflight that fails explicitly and names the offending component LCOV when a CI-critical artifact is missing or empty, instead of silently treating it as 0%. Was AC14.1.20.",
            test="tests/tooling/test_coverage_artifact_preflight.py::test_AC14_1_20_preflight_fails_when_ci_critical_artifact_missing",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.coverage-tiers.2",
            statement="Coverage components carry an explicit tier (ci-critical vs best-effort); the artifact preflight enforces presence only for ci-critical tiers so a missing best-effort tools artifact does not hard-fail aggregation. Was AC14.1.21.",
            test="tests/tooling/test_coverage_artifact_preflight.py::test_AC14_1_21_tools_component_is_best_effort_tier",
            priority="P1",
            status="done",
        ),
        # ── migration-risk: database migration risk governance (was EPIC-007
        # AC7.11, migration closeout wave 3, #1663) ──
        ACRecord(
            id="AC-meta.migration-risk.1",
            statement=(
                "Every backend Alembic migration is covered by a "
                "machine-readable migration risk manifest."
            ),
            test=(
                "tests/tooling/test_migration_risk_contract.py"
                "::test_AC7_11_1_migration_risk_manifest_covers_backend_migrations"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.migration-risk.2",
            statement=(
                "High and critical migration risk entries require release "
                "proof notes covering staging validation, production "
                "preflight, and a rollback/expand-contract strategy."
            ),
            test=(
                "tests/tooling/test_migration_risk_contract.py"
                "::test_AC7_11_2_high_and_critical_migrations_require_release_proof"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.migration-risk.3",
            statement=(
                "A destructive upgrade operation cannot be classified below "
                "critical risk."
            ),
            test=(
                "tests/tooling/test_migration_risk_contract.py"
                "::test_AC7_11_3_destructive_migrations_must_be_classified_critical"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.migration-risk.4",
            statement=(
                "CI lint and the production release dry-run both execute the "
                "migration risk contract and publish its release context."
            ),
            test=(
                "tests/tooling/test_migration_risk_contract.py"
                "::test_AC7_11_4_ci_and_release_dry_run_execute_migration_risk_contract"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.migration-risk.5",
            statement=(
                "Risk is auto-classified from each migration's upgrade() body "
                "(destructive->critical, data-mutation->high, "
                "compatibility-sensitive->medium, else low); low/medium "
                "migrations need no manifest entry, while auto-classified "
                "high/critical migrations require an explicit release-proof "
                "entry."
            ),
            test=(
                "tests/tooling/test_migration_risk_contract.py"
                "::test_AC7_11_5_low_and_medium_migrations_are_auto_classified"
            ),
            priority="P0",
            status="done",
        ),
        # ── release-pipeline: promote-not-rebuild release integrity (was
        # EPIC-007 AC7.10, migration closeout wave 3, #1663) ──
        ACRecord(
            id="AC-meta.release-pipeline.1",
            statement=(
                "The production release workflow promotes the staging-"
                "validated `:<sha>` image to `vX.Y.Z` via `docker buildx "
                "imagetools create` instead of rebuilding from source; fails "
                "closed if no staging-validated SHA image exists or if the "
                "promoted digest differs from the staging-verified digest; "
                "records the released commit, source CI run, and promoted "
                "image digest in the workflow summary; keeps the SSOTs "
                "(ci-cd.md, deployment.md) documenting the promote-not-"
                "rebuild consistency ladder; and retains a `workflow_dispatch` "
                "dry-run that proves the release/promote path without "
                "mutating production."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC7_10_production_release_promotes_not_rebuilds"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        # ── infra-boundary: delivery app/infra-boundary calibration (was
        # EPIC-007 AC7.12, #876, migration closeout wave 3, #1663) ──
        ACRecord(
            id="AC-meta.infra-boundary.1",
            statement=(
                "Finance Report staging/prod workflows render canonical deploy requests and "
                "do not read or execute infra2 source."
            ),
            test=(
                "tests/tooling/test_app_deploy_request.py"
                "::test_AC_runtime_deploy_request_4_repository_has_no_infra2_source_edge"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.infra-boundary.2",
            statement=(
                "infra2 owns compose, data persistence, Vault injection, and Dokploy behavior; "
                "the app crosses the boundary only through the versioned request contract."
            ),
            test=(
                "tests/tooling/test_app_deploy_request.py"
                "::test_AC_runtime_deploy_request_4_repository_has_no_infra2_source_edge"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.infra-boundary.3",
            statement=(
                "ci.yml's on.push.branches includes release/** so a release-"
                "branch commit publishes a :<sha> image."
            ),
            test=(
                "tests/tooling/test_publish_only_contract.py"
                "::test_AC7_12_4_release_branches_trigger_the_publish_workflow"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.infra-boundary.4",
            statement=(
                "The container-image push: conditions cover main, release-"
                "branch, and workflow_dispatch triggers."
            ),
            test=(
                "tests/tooling/test_publish_only_contract.py"
                "::test_AC7_12_4_image_push_publishes_for_main_release_and_dispatch"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.infra-boundary.5",
            statement=(
                "The persistent Dokploy preview (deploy-preview) runs only "
                "via manual workflow_dispatch, never per-PR auto-deploy, "
                "while the in-runner e2e merge gate stays automatic."
            ),
            test=(
                "tests/tooling/test_publish_only_contract.py"
                "::test_AC7_12_4_persistent_preview_is_on_demand_not_per_pr"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.infra-boundary.6",
            statement=(
                "environments.md defines the derived data-lane contract for "
                "deploy_v2(service, type, version_ref, iac_ref) — the current "
                "data sources/defaults and the four data red lines (a PR sha "
                "never runs on prod data; prod data is anonymized before "
                "leaving prod; non-prod object storage holds no real "
                "uploads; a backup is not an anonymized snapshot)."
            ),
            test=(
                "tests/tooling/test_data_red_lines_contract.py"
                "::test_AC7_12_6_environments_define_data_axis_and_red_lines"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.infra-boundary.7",
            statement=(
                "The root SSOT does not drift back to the retired public-"
                "axis deploy primitive; the data lane stays derived from "
                "the deploy_v2 coordinate."
            ),
            test=(
                "tests/tooling/test_data_red_lines_contract.py"
                "::test_AC7_12_6_deploy_v2_data_lane_is_derived_not_public_axis"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.infra-boundary.8",
            statement=(
                "The published :<sha> frontend image is environment-"
                "independent (same-origin /api, no concrete environment "
                "domain baked in)."
            ),
            test=(
                "tests/tooling/test_frontend_same_origin_contract.py"
                "::test_AC7_12_8_published_frontend_image_has_no_baked_env_domain"
            ),
            priority="P0",
            status="done",
        ),
        # ── delivery: the sanctioned app delivery layer (#1763 ruling).
        # routers/ + schemas/ + the composition root are hexagonal primary
        # adapters of the application, not domain behavior — sanctioned, not
        # dissolved; the sanction's teeth are the thin-ness ratchet below. ──
        ACRecord(
            id="AC-meta.delivery.1",
            statement=(
                "routers/ (HTTP delivery adapters) and schemas/ (API DTOs) "
                "are the sanctioned app delivery layer (#1763): routing and "
                "serialization glue only, whose bulk may only shrink as "
                "packages absorb logic. The per-directory line census of "
                "apps/backend/src/{routers,schemas} (*.py, recursive) must "
                "stay within a 50-line band of "
                "common/meta/data/delivery-layer-baseline.json: growth beyond the "
                "band fails CI and requires raising the baseline in the same "
                "PR, where the diff makes the choice reviewable (the "
                "app-boundary idiom) — legitimate only for genuine delivery "
                "glue, never domain logic; shrink beyond the band lowers the "
                "baseline in the same PR so the ratchet stays tight. "
                "prompts/ is deliberately outside the census — domain "
                "content, not delivery; it dissolves into its owning "
                "packages (reconciliation's lives at "
                "src/reconciliation/base/prompts.py since PR #1748; "
                "advisor's moves with #1671 Wave B)."
            ),
            test=(
                "tests/tooling/test_delivery_layer_ratchet.py"
                "::test_AC_meta_delivery_1_delivery_layer_only_thins"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.delivery.2",
            statement=(
                "The terminal HTTP API home is each owning package's "
                "extension/api/ adapter. apps/backend/src/routers remains a "
                "transitional delivery layer whose non-__init__.py file set "
                "may only shrink relative to the committed baseline; a new "
                "flat router fails CI and --update refuses to adopt it "
                "(#1865 S2 G-one-home-decided)."
            ),
            test=(
                "tests/tooling/test_api_surface_ratchet.py"
                "::test_AC_meta_delivery_2_router_file_set_only_shrinks"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.delivery.3",
            statement=(
                "Package base layers never import src.schemas; that forbidden "
                "edge has no baseline or exemption. Outside base/, the count "
                "of package files importing src.schemas may only shrink "
                "relative to the committed baseline; a new package dependency "
                "fails CI and --update refuses to raise the baseline (#1865 "
                "S2 G-dependency-direction)."
            ),
            test=(
                "tests/tooling/test_api_surface_ratchet.py"
                "::test_AC_meta_delivery_3_package_schema_import_count_only_shrinks"
            ),
            priority="P1",
            status="done",
        ),
        # ── residue: the post-migration EPIC tables hold only explicitly
        # marked residue (#1719 "retire the center"; #1416 DoD addition
        # 2026-07-11 makes "genuinely EPIC-owned" machine-checkable). ──
        ACRecord(
            id="AC-meta.residue.1",
            statement=(
                "Every AC definition line that stays in a docs/project/"
                "EPIC-*.md doc carries an explicit residue marker "
                "(<!-- epic-owned: fe-only|fe-half|horizontal|"
                "pending-package -->) declaring why it is not in a package "
                "roadmap; unmarked EPIC AC rows == 0 is the umbrella "
                "scoreboard metric. The per-file per-category census must "
                "equal common/meta/data/epic-residue-baseline.json (the "
                "fk-cascade idiom): silent residue growth fails CI and "
                "adding residue requires raising the baseline in the same "
                "PR, where the diff makes the choice reviewable; the EPIC "
                "file set may only shrink (a new EPIC file fails; a deleted "
                "one must prune the baseline); an EPIC file with zero "
                "marked rows must carry an explicit <!-- epic-file: "
                "design-doc|goal-stub --> justification. The registry "
                "generator feeds the AC registry from marked rows only, so "
                "an unmarked row is invisible to the registry AND fails the "
                "gate."
            ),
            test=(
                "tests/tooling/test_epic_residue_ratchet.py"
                "::test_AC_meta_residue_1_census_equals_baseline_and_files_only_shrink"
            ),
            priority="P0",
            status="done",
        ),
        # ── terminal: both retired centers (docs/ssot/ entirely, and
        # docs/project/'s file set) cannot silently regrow (#1823,
        # Package-ization 4/4, FINAL — "retire the center" closeout). ──
        ACRecord(
            id="AC-meta.residue.2",
            statement=(
                "docs/ssot/ does not exist (retired in #1823: MANIFEST.yaml "
                "and epic-residue-baseline.json relocated to "
                "common/meta/data/, README.md tombstone retired), and "
                "docs/project/'s directory listing is frozen to an explicit, "
                "checked-in allowlist — the EPIC-*.md half sourced from "
                "AC-meta.residue.1's own baseline (single source, no "
                "duplicated vocabulary), the non-EPIC half a hardcoded "
                "frozenset. Either directory growing outside its allowlist "
                "fails CI; a deliberate addition requires a same-PR edit "
                "here, making the choice reviewable — the same fk-cascade "
                "idiom AC-meta.residue.1 uses for EPIC file counts."
            ),
            test=(
                "tests/tooling/test_terminal_centers_allowlist.py"
                "::test_docs_project_directory_listing_is_frozen"
            ),
            priority="P1",
            status="done",
        ),
        # ── manifest: common/meta/data/MANIFEST.yaml stays hand-authored (a
        # full computed concept index is a follow-up, #1799). Relocated from
        # docs/ssot/ in #1823 (Package-ization 4/4); the former per-file
        # docs/ssot/ classification check (#1664 "retire the center", Part C)
        # is superseded by AC-meta.residue.2's docs/ssot-absence assertion,
        # which is strictly stronger (nothing can exist there uncatalogued,
        # vs. everything that exists must be catalogued). ──
        ACRecord(
            id="AC-meta.manifest.1",
            statement=(
                "The residual (no-owning-package) concept-ownership registry "
                "lives at common/meta/data/MANIFEST.yaml — a package's "
                "cross-cutting gate-data home, not a hand-classified "
                "docs/ssot/ (retired)."
            ),
            test=(
                "tests/tooling/test_check_manifest.py"
                "::test_AC_meta_manifest_1_manifest_relocated_and_ssot_retired"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.manifest.2",
            statement=(
                "check_manifest.py validates the computed UNION of the "
                "residual MANIFEST.yaml and every package's own "
                "`concepts=[ConceptRecord(...), ...]` declaration "
                "(`concept_index`, the concept-registry mirror of "
                "`contract_index`'s `ac_index` for roadmap ACs, #1799): no "
                "two concepts (from either source) share an owner or a key, "
                "every owner/cross_ref file and #anchor resolves on disk."
            ),
            test=(
                "tests/tooling/test_check_manifest.py"
                "::test_AC_meta_manifest_2_concept_from_package_contract_is_validated"
            ),
            priority="P2",
            status="done",
        ),
        # ── group phase0: EPIC-001 phase-0 scaffolding + EPIC-007 static infra
        # contracts (was EPIC-001 AC1.1.1-1.6.1 and EPIC-007 AC7.8.1-3, #1821
        # Wave A horizontal move). AC1.4.1/AC7.8.2 shared one test (Docker
        # compose integrity) and are merged into `.11`; AC1.5.1/AC7.8.3 shared
        # one test (moon project graph contract) and are merged into `.15`. ──
        ACRecord(
            id="AC-meta.phase0.1",
            statement="Root moon.yml exists.",
            test="apps/backend/tests/infra/test_epic_001_contracts.py::test_epic_001_moon_workspace_configs_exist",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.2",
            statement="apps/backend/moon.yml exists.",
            test="apps/backend/tests/infra/test_epic_001_contracts.py::test_epic_001_moon_workspace_configs_exist",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.3",
            statement="apps/frontend/moon.yml exists.",
            test="apps/backend/tests/infra/test_epic_001_contracts.py::test_epic_001_moon_workspace_configs_exist",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.4",
            statement="tools/infra.sh local infrastructure command exists.",
            test="apps/backend/tests/infra/test_epic_001_contracts.py::test_epic_001_moon_workspace_configs_exist",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.5",
            statement="The FastAPI project structure exists (apps/backend skeleton).",
            test="apps/backend/tests/infra/test_epic_001_contracts.py::test_epic_001_backend_skeleton_exists",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.6",
            statement=(
                "SQLAlchemy + Alembic config is valid: no missing migrations "
                "and a single Alembic head (also proven by test_single_head "
                "in apps/backend/tests/infra/test_migrations.py)."
            ),
            test="apps/backend/tests/infra/test_schema_drift.py::test_missing_migrations_check",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.7",
            statement="Next.js App Router files exist.",
            test="apps/backend/tests/infra/test_epic_001_contracts.py::test_epic_001_frontend_skeleton_exists",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.8",
            statement="TailwindCSS configuration exists.",
            test="apps/backend/tests/infra/test_epic_001_contracts.py::test_epic_001_frontend_skeleton_exists",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.9",
            statement="The ping-pong page exists.",
            test="apps/backend/tests/infra/test_epic_001_contracts.py::test_epic_001_frontend_skeleton_exists",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.10",
            statement="TanStack Query dependency is configured.",
            test="apps/backend/tests/infra/test_epic_001_contracts.py::test_epic_001_frontend_uses_react_query",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.11",
            statement="docker-compose.yml integrity is valid.",
            # was AC1.4.1 + AC7.8.2 (identical test, merged)
            test="apps/backend/tests/infra/test_ci_config.py::test_docker_compose_integrity",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.12",
            statement="PostgreSQL 15 container is defined in docker-compose.",
            test="apps/backend/tests/infra/test_epic_001_contracts.py::test_epic_001_docker_compose_contract",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.13",
            statement="Redis 7 container is defined in docker-compose.",
            test="apps/backend/tests/infra/test_epic_001_contracts.py::test_epic_001_docker_compose_contract",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.14",
            statement="Data volumes are configured in docker-compose.",
            test="apps/backend/tests/infra/test_epic_001_contracts.py::test_epic_001_docker_compose_contract",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.15",
            statement=(
                "The Moon project graph contract is declared in repo config "
                "(backend startup command path resolves through it)."
            ),
            # was AC1.5.1 + AC7.8.3 (identical test, merged)
            test="apps/backend/tests/infra/test_ci_config.py::test_moon_project_graph_static_contract",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.16",
            statement="The frontend startup command path is valid (Moon task configured).",
            test="apps/backend/tests/infra/test_epic_001_contracts.py::test_epic_001_frontend_moon_tasks_configured",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.17",
            statement="The backend ping-pong endpoint toggles state correctly.",
            test="apps/backend/tests/infra/test_main.py::test_ping_toggle",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.18",
            statement="Pre-commit hooks configuration is present.",
            test="apps/backend/tests/infra/test_epic_001_contracts.py::test_epic_001_pre_commit_config_exists",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.phase0.19",
            statement=(
                "The Moon local CLI contract is versioned without a PR CI "
                "bootstrap dependency."
            ),
            # was AC7.8.1
            test="apps/backend/tests/infra/test_ci_config.py::test_moon_cli_static_contract_available",
            priority="P1",
            status="done",
        ),
        # ── group framework-neutrality: canonical ledger/reporting stay
        # US/HK-framework-neutral, policy decisions belong to EPIC-020 (was
        # EPIC-002 AC2.18.1 and EPIC-005 AC5.14.1, #1821 Wave A horizontal
        # move) ──
        ACRecord(
            id="AC-meta.framework-neutrality.1",
            statement=(
                "Canonical ledger documentation declares that double-entry "
                "posting is framework-neutral and that US/HK policy "
                "decisions belong to EPIC-020."
            ),
            # was AC2.18.1
            test=(
                "tests/tooling/test_framework_reporting_epic_contract.py"
                "::test_AC2_18_1_canonical_ledger_is_framework_neutral"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.framework-neutrality.2",
            statement=(
                "Reporting docs declare that EPIC-005 consumes framework "
                "policy results for US/HK package output and does not own "
                "framework-specific accounting decisions."
            ),
            # was AC5.14.1
            test=(
                "tests/tooling/test_framework_reporting_epic_contract.py"
                "::test_AC5_14_1_reporting_assembles_framework_policy_results_only"
            ),
            priority="P1",
            status="done",
        ),
        # NOTE: the "archive-residual" rows (was EPIC-004 AC4.8.1, EPIC-008
        # AC8.13.61-.63, EPIC-012 AC12.25.1) were evaluated for this move and
        # REJECTED: their own proving test
        # (tests/tooling/test_archive_residual_epic_ownership.py) asserts
        # that the AC id and description text are still literally present
        # IN THE EPIC DOC (e.g. `assert "AC8.13.61" in epic`) — the test's
        # entire purpose is confirming the row stays EPIC-owned. Deleting the
        # row to migrate it would make the test that is supposed to prove
        # "this is intentionally still EPIC-owned" fail. These rows are left
        # untouched as `horizontal` (#1821 Wave A).
        # ── group transaction-boundary: cross-service commit/flush boundary
        # discipline (was EPIC-012 AC12.26.1-.3, #1821 Wave A horizontal
        # move) ──
        ACRecord(
            id="AC-meta.transaction-boundary.1",
            statement=(
                "Service modules only call commit() in documented "
                "background-task or streaming-response transaction-boundary "
                "exceptions."
            ),
            # was AC12.26.1
            test=(
                "apps/backend/tests/infra/test_transaction_boundaries.py"
                "::test_service_commit_calls_are_documented_boundary_exceptions"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.transaction-boundary.2",
            statement=(
                "Market-data persistence helpers use flush() so router/"
                "report/scheduler boundaries can roll back or commit "
                "atomically."
            ),
            # was AC12.26.2
            test=(
                "apps/backend/tests/infra/test_transaction_boundaries.py"
                "::test_market_data_fx_persistence_is_rollbackable_until_boundary_commit"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.transaction-boundary.3",
            statement=(
                "Market-data HTTP sync endpoints finalize service writes at "
                "the router boundary."
            ),
            # was AC12.26.3
            test=(
                "apps/backend/tests/infra/test_transaction_boundaries.py"
                "::test_market_data_sync_endpoint_commits_service_writes_at_router_boundary"
            ),
            priority="P1",
            status="done",
        ),
        # ── group workflow-events: workflow-events SSOT documents frontend
        # surfaces (was EPIC-019 AC19.3.8, #1821 Wave A horizontal move) ──
        ACRecord(
            id="AC-meta.workflow-events.1",
            statement=(
                "The workflow notification UI contract is documented in the "
                "workflow-events SSOT and EPIC-019."
            ),
            # was AC19.3.8
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_3_8_workflow_notification_ssot_documents_frontend_surfaces"
            ),
            priority="P1",
            status="done",
        ),
        # NOTE: AC26.9.1 (the CODE/LLM band classifier's own test) was
        # evaluated for this move and REJECTED, confirming EPIC-026's own
        # documented reasoning: its proving test is itself marker-laden (it
        # exercises cassette detection), so `check_authority_reconcile.py`
        # detects the roadmap as CODE-LED (1 LLM-classified test) the moment
        # it is added to `meta`'s roadmap, tripping meta's declared
        # CODE-ONLY tier (verified: `code=88 llm=1` after a trial add).
        # AC26.9.1 is left untouched as `horizontal` (#1821 Wave A).
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-016
        # (two-stage-review-ui) ──
        ACRecord(
            id="AC-meta.fe-utils.1",
            statement="`formatDateInput` formats `Date` as `YYYY-MM-DD` with zero-padded month and day",
            # was AC16.6.1
            test="apps/frontend/src/__tests__/date.test.ts::AC16.6.1 formats a date as YYYY-MM-DD string",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.1",
            statement="`apiFetch` returns JSON on `200` response",
            # was AC16.10.1
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.1 returns JSON on 200 response",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.1",
            statement="Ping-pong page loads initial state and displays current ping/pong value",
            # was AC16.12.8
            test="apps/frontend/src/__tests__/pingPongPage.test.tsx::AC16.12.8 loads initial state and shows current value",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-utils.2",
            statement="Formats a Date object to en-US short date",
            # was AC16.6.2
            test="apps/frontend/src/__tests__/date.test.ts::AC16.6.2 formats a Date object to en-US short date",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.2",
            statement="`apiFetch` returns `undefined` on `204 No Content`",
            # was AC16.10.2
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.2 returns undefined on 204 No Content",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.2",
            statement="Ping-pong page toggles state and updates toggle count on button click",
            # was AC16.12.9
            test="apps/frontend/src/__tests__/pingPongPage.test.tsx::AC16.12.9 toggles state and updates count",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-utils.3",
            statement="Formats a Date object with date and time",
            # was AC16.6.3
            test="apps/frontend/src/__tests__/date.test.ts::AC16.6.3 formats a Date object with date and time",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.3",
            statement="`apiFetch` throws error with `detail` message on non-ok response",
            # was AC16.10.3
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.3 throws with detail message on JSON error response",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.3",
            statement="Ping-pong page renders retry flow when initial load fails",
            # was AC16.12.10
            test="apps/frontend/src/__tests__/pingPongPage.test.tsx::AC16.12.10 renders retry flow on initial error",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-utils.4",
            statement="Returns short month name from date string",
            # was AC16.6.4
            test="apps/frontend/src/__tests__/date.test.ts::AC16.6.4 returns short month name from date string",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.4",
            statement="`apiFetch` throws on non-JSON error text",
            # was AC16.10.4
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.4 throws with raw text on non-JSON error response",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.4",
            statement="Root resolves to the authenticated Home entry (superseded by EPIC-022)",
            # was AC16.16.1
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC19.4.2 AC16.16.1 renders the upload-to-report home before secondary dashboard metrics",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-utils.5",
            statement="`getTheme` returns stored value or system preference",
            # was AC16.7.1
            test="apps/frontend/src/__tests__/theme.test.ts::AC16.7.1 returns stored dark theme from localStorage",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.5",
            statement="`apiFetch` calls `handle401Redirect` on `401` response",
            # was AC16.10.5
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.5 redirects to /login on 401 unauthorized response",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.5",
            statement="Main layout renders children through `AppShell` wrapper",
            # was AC16.16.2
            test="apps/frontend/src/__tests__/mainLayout.test.tsx::AC16.16.2 renders children through AppShell",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-utils.6",
            statement="`setTheme` adds/removes `dark` CSS class and saves to `localStorage`",
            # was AC16.7.2
            test="apps/frontend/src/__tests__/theme.test.ts::AC16.7.2 adds dark class when setting dark theme",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.6",
            statement="`resetRedirectGuard` resets the redirect guard state",
            # was AC16.10.6
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.6 resetRedirectGuard is exported and callable",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.6",
            statement="Root layout composes `Providers` and `AuthGuard` around children",
            # was AC16.17.5
            test="apps/frontend/src/__tests__/rootLayout.test.tsx::AC16.17.5 composes Providers and AuthGuard around children",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-utils.7",
            statement="`toggleTheme` switches between dark and light",
            # was AC16.7.3
            test="apps/frontend/src/__tests__/theme.test.ts::AC16.7.3 toggles from light to dark",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.7",
            statement="`apiDelete` succeeds on `200` response",
            # was AC16.10.7
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.7 succeeds on 200 response",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.7",
            statement="`Providers` wraps children with `QueryClientProvider`",
            # was AC16.17.6
            test="apps/frontend/src/__tests__/providers.test.tsx::AC16.17.6 wraps children with QueryClientProvider",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-utils.8",
            statement="`initTheme` applies stored or system theme on load",
            # was AC16.7.4
            test="apps/frontend/src/__tests__/theme.test.ts::AC16.7.4 initializes theme from stored value",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.8",
            statement="`apiDelete` throws on non-ok response",
            # was AC16.10.8
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.8 throws on non-ok response",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.8",
            statement="Sidebar shows auth-aware actions and logout triggers `clearUser` plus login redirect",
            # was AC16.19.3
            test="apps/frontend/src/__tests__/sidebarAndTabs.test.tsx::AC16.19.3 AC22.21.2 shows auth-aware sidebar actions mirroring the bottom tabs",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.9",
            statement="`apiStream` returns response and `sessionId` on success",
            # was AC16.10.9
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.9 returns response and sessionId on success",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.9",
            statement="Workspace tabs derive route labels and invoke add/set/remove tab handlers",
            # was AC16.19.4
            test="apps/frontend/src/__tests__/sidebarAndTabs.test.tsx::AC16.19.4 adds and manages workspace tabs from route changes",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.10",
            statement="`apiStream` throws on non-ok response",
            # was AC16.10.10
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.10 throws on non-ok response",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.10",
            statement="Confirm dialog handles required input, cancel, and confirm interactions",
            # was AC16.19.7
            test="apps/frontend/src/__tests__/confirmDialogComponent.test.tsx::AC16.19.7 handles required input and confirm/cancel",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.11",
            statement="`apiUpload` returns JSON on `200` response",
            # was AC16.10.11
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.11 returns JSON on 200 response",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.11",
            statement="Confirm dialog responds to escape key and backdrop click when not loading",
            # was AC16.19.8
            test="apps/frontend/src/__tests__/confirmDialogComponent.test.tsx::AC16.19.8 AC16.30.4 handles escape and backdrop cancellation",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.12",
            statement="`apiUpload` returns `undefined` on `204 No Content`",
            # was AC16.10.12
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.12 returns undefined on 204 No Content",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.12",
            statement="Toast provider shows, dismisses, and auto-expires notifications",
            # was AC16.19.9
            test="apps/frontend/src/__tests__/toastProviderComponent.test.tsx::AC16.19.9 shows and dismisses notifications",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.13",
            statement="`apiFetch` normalizes path without leading slash",
            # was AC16.10.13
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.13 normalizes path without leading slash",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.13",
            statement="Keeps the accounting machinery, sidebar badges and settings out of the sidebar (supersedes the Advanced drawer)",
            # was AC16.19.12
            test="apps/frontend/src/__tests__/sidebarAndTabs.test.tsx::AC15.7.7 AC16.19.12 AC19.6.3 AC19.6.4 AC19.6.5 AC22.21.1 keeps the accounting machinery, sidebar badges and settings out of the sidebar (supersedes the Advanced drawer)",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.14",
            statement="`apiFetch` includes `Authorization` header when token is present",
            # was AC16.10.14
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.14 includes Authorization header when token present",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.14",
            statement="WorkspaceTabs labels /assets tab as Portfolio from ROUTE_CONFIG",
            # was AC16.19.13
            test="apps/frontend/src/__tests__/sidebarAndTabs.test.tsx::AC16.19.13 WorkspaceTabs labels /assets tab as Portfolio from ROUTE_CONFIG",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.15",
            statement="Handles 401 redirect in apiDelete",
            # was AC16.10.15
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.15 handles 401 redirect in apiDelete",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.15",
            statement="WorkspaceTabs section header is Open Tabs in both empty and active states",
            # was AC16.19.14
            test="apps/frontend/src/__tests__/sidebarAndTabs.test.tsx::AC16.19.14 WorkspaceTabs section header is Open Tabs in both empty and active states",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.16",
            statement="Includes Authorization header when token present",
            # was AC16.10.16
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.16 includes Authorization header when token present",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.16",
            statement="Navigates workspace pages with ArrowRight keyboard",
            # was AC16.19.15
            test="apps/frontend/src/__tests__/sidebarAndTabs.test.tsx::AC16.19.15 AC16.30.3 AC16.30.4 navigates workspace pages with ArrowRight keyboard",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.17",
            statement="Handles 401 redirect in apiUpload",
            # was AC16.10.17
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.17 handles 401 redirect in apiUpload",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.17",
            statement="Renders dialog with ARIA attributes",
            # was AC16.19.16
            test="apps/frontend/src/__tests__/confirmDialogComponent.test.tsx::AC16.19.16 AC16.30.4 renders dialog with ARIA attributes",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.18",
            statement="Throws with detail message on JSON error response",
            # was AC16.10.18
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.18 throws with detail message on JSON error response",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.18",
            statement="Traps focus with Tab and Shift+Tab",
            # was AC16.19.17
            test="apps/frontend/src/__tests__/confirmDialogComponent.test.tsx::AC16.19.17 AC16.30.4 traps focus with Tab and Shift+Tab",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.19",
            statement="Throws with raw text on non-JSON error response",
            # was AC16.10.19
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC16.10.19 throws with raw text on non-JSON error response",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.19",
            statement="Workspace provider restores tabs from storage and persists active workspace updates",
            # was AC16.21.9
            test="apps/frontend/src/__tests__/useWorkspaceHook.test.tsx::AC16.21.9 hydrates tabs from localStorage and keeps active tab",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.20",
            statement="API catch-all handlers return JSON `503` for all HTTP methods",
            # was AC16.17.7
            test="apps/frontend/src/__tests__/apiCatchAllRoute.test.ts::AC16.17.7 returns 503 JSON for all supported methods",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.20",
            statement="Workspace provider handles tab deduplication, removal, and cross-tab storage sync",
            # was AC16.21.10
            test="apps/frontend/src/__tests__/useWorkspaceHook.test.tsx::AC16.21.10 deduplicates tabs by href and keeps existing active id",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.21",
            statement="Root layout keeps theme color in the viewport export and avoids duplicate iOS web-app capability metadata",
            # was AC16.25.4
            test="apps/frontend/src/__tests__/rootLayout.test.tsx::AC16.25.4 root layout metadata keeps viewport-only theme color",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.22",
            statement="Shared React UI primitives live under `apps/frontend/src/components/ui/` and cover button, icon button, badge, alert, empty state, loading state, and page header usage without requiring page-local class recipes",
            # was AC16.28.1
            test="apps/frontend/src/__tests__/uiPrimitives.test.tsx::AC16.28.1 AC16.28.4 renders button and badge variants through shared primitives",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.23",
            statement="Icon-only actions require an accessible label through the primitive API and representative account/statement delete-edit actions use those labels",
            # was AC16.28.2
            test="apps/frontend/src/__tests__/uiPrimitives.test.tsx::AC16.28.2 AC16.28.4 requires icon-only actions to expose an accessible label",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.24",
            statement="At least two representative frontend pages are migrated to the primitive layer without changing their existing workflows or API calls",
            # was AC16.28.3
            test="apps/frontend/src/__tests__/accountsPage.test.tsx::AC16.28.2 AC16.28.3 exposes account row icon actions with accessible labels",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.25",
            statement="Primitive component tests cover variants, accessibility-facing props, and the migrated loading/error/empty states",
            # was AC16.28.4
            test="apps/frontend/src/__tests__/uiPrimitives.test.tsx::AC16.28.1 AC16.28.4 renders button and badge variants through shared primitives",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.26",
            statement="Tailwind theme extension maps frontend CSS-variable tokens for semantic color, radius, shadow/elevation, z-index, motion, typography, and chart palette usage",
            # was AC16.29.1
            test="apps/frontend/src/__tests__/designTokens.test.tsx::AC16.29.1 AC16.29.4 maps Tailwind theme values to CSS-variable design tokens",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.27",
            statement="Frontend CSS and SSOT document the design-token model, including token usage rules and intentional page-local visual choices such as login/dashboard gradients, shadows, and radius",
            # was AC16.29.2
            test="apps/frontend/src/__tests__/designTokens.test.tsx::AC16.29.2 AC16.29.4 documents token usage and page-local visual decisions in SSOT",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.28",
            statement="Confidence and status UI components use semantic token-backed primitives instead of hardcoded Tailwind palette utilities across all confidence/status variants",
            # was AC16.29.3
            test="apps/frontend/src/__tests__/designTokens.test.tsx::AC16.29.3 AC16.29.4 renders ConfidenceBadge variants through semantic token classes",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.29",
            statement="Frontend tests cover the token configuration contract and at least one tokenized semantic component across multiple variants",
            # was AC16.29.4
            test="apps/frontend/src/__tests__/designTokens.test.tsx::AC16.29.1 AC16.29.4 maps Tailwind theme values to CSS-variable design tokens",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.30",
            statement="`IconButton` keeps its required `label` as the authoritative accessible name so callers cannot override or remove it through passthrough props",
            # was AC16.30.1
            test="apps/frontend/src/__tests__/uiPrimitives.test.tsx::AC16.30.1 AC16.30.4 keeps IconButton label authoritative over passthrough props",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.31",
            statement="The design-token follow-ups from issues #612 and #613 are resolved: border tokens are documented, core recipes use `border-border`, alert variants use semantic status token classes, and SSOT examples use accurate fence language",
            # was AC16.30.2
            test="apps/frontend/src/__tests__/designTokens.test.tsx::AC16.30.2 AC16.30.6 keeps SSOT and CSS recipes on semantic border and status tokens",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.32",
            statement="`WorkspaceTabs` uses one coherent navigation/list semantic model with `aria-current` for the active route while preserving keyboard navigation between open workspace pages",
            # was AC16.30.3
            test="apps/frontend/src/__tests__/sidebarAndTabs.test.tsx::AC16.19.15 AC16.30.3 AC16.30.4 navigates workspace pages with ArrowRight keyboard",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.33",
            statement="Component tests cover keyboard and ARIA behavior for dialog, sheet, toast, workspace navigation, and icon-only controls",
            # was AC16.30.4
            test="apps/frontend/src/__tests__/confirmDialogComponent.test.tsx::AC16.19.8 AC16.30.4 handles escape and backdrop cancellation",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.34",
            statement="Playwright visual smoke covers desktop and mobile representative app-shell, accounts, statements, and review pages with stable visual anchors and nonblank screenshots",
            # was AC16.30.5
            test="apps/frontend/playwright/ui-visual-smoke.spec.ts::captures representative app-shell, accounts, statements, and review pages",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell.35",
            statement="Frontend SSOT documents the accessibility and visual-verification workflow required for future UI-system changes",
            # was AC16.30.6
            test="apps/frontend/src/__tests__/designTokens.test.tsx::AC16.30.2 AC16.30.6 keeps SSOT and CSS recipes on semantic border and status tokens",
            priority="P2",
            status="done",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-022
        # (everyday-user-ia) and EPIC-005 (reporting-visualization) ──
        ACRecord(
            id="AC-meta.fe-ia-nav.1",
            statement="Primary navigation renders a bottom tab bar of exactly five hit targets — Home, Chat, a center Add action, Audit, and More — mirrored by the desktop sidebar; no accounting-jargon route (Journal, Reconciliation, Accounts, Statements) and no Settings page appears as a top-level tab (superseded by AC22.21.1 for the data-model shape)",
            # was AC22.1.1
            test="apps/frontend/src/__tests__/navigation.test.ts::AC19.6.2 AC19.8.5 AC22.1.1 AC22.1.7 AC22.2.4 AC22.21.1 exposes a five-target bottom tab bar with distinct icons (Home, Chat, Add, Audit, More)",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.2",
            statement="The sidebar brand links to `/` and the login flow redirects to `/` after authentication",
            # was AC22.1.3
            test="apps/frontend/src/__tests__/sidebarAndTabs.test.tsx::AC22.1.3 links the sidebar brand to Home",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.3",
            statement='`/dashboard` redirects to `/` and the label "Upload Pipeline" no longer appears in the navigation model',
            # was AC22.1.4
            test="apps/frontend/src/__tests__/nextConfigRedirects.test.ts::AC22.1.4 redirects the legacy dashboard route to Home",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.4",
            statement="`/events` redirects to `/notifications` and the notifications page renders the workflow event center",
            # was AC22.1.5
            test="apps/frontend/src/__tests__/nextConfigRedirects.test.ts::AC22.1.5 redirects /events to /notifications",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.5",
            statement='`/assets` redirects to `/portfolio` and exactly one navigation entry is labeled "Portfolio"',
            # was AC22.1.6
            test="apps/frontend/src/__tests__/navigation.test.ts::AC22.1.6 lists Portfolio exactly once across the navigation model",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.6",
            statement="Chat and AI Settings navigation entries use distinct icons",
            # was AC22.1.7
            test="apps/frontend/src/__tests__/navigation.test.ts::AC19.6.2 AC19.8.5 AC22.1.1 AC22.1.7 AC22.2.4 AC22.21.1 exposes a five-target bottom tab bar with distinct icons (Home, Chat, Add, Audit, More)",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.7",
            statement="`/upload` renders both the statement uploader and upload history, and `/statements/upload` redirects to `/upload`",
            # was AC22.1.8
            test="apps/frontend/src/__tests__/nextConfigRedirects.test.ts::AC22.1.8 redirects legacy statement routes to /upload",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.8",
            statement="Desktop and mobile smoke covers the five-target bottom-tab navigation (Home, Chat, Add, Audit, More) and the notification bell without layout overflow",
            # was AC22.1.9
            test="apps/frontend/playwright/epic022-ia-shell.spec.ts::desktop sidebar mirrors the five bottom-tab targets and the notification bell",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.9",
            statement='The standalone Review Queue page is removed, `/review` redirects to `/notifications`, and "Review" is no longer a sidebar navigation entry',
            # was AC22.2.4
            test="apps/frontend/src/__tests__/navigation.test.ts::AC19.6.2 AC19.8.5 AC22.1.1 AC22.1.7 AC22.2.4 AC22.21.1 exposes a five-target bottom tab bar with distinct icons (Home, Chat, Add, Audit, More)",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.10",
            statement="The upload, statement-detail, and statement-review pages render a shared step indicator showing the Upload → Review & approve → Reports path with the current step highlighted",
            # was AC22.5.1
            test="apps/frontend/src/__tests__/flowStepBanner.test.tsx::AC22.5.1 renders the Upload -> Review & approve -> Reports path",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.11",
            statement='Core jargon terms (balance "drift"/"balanced", "needs review", transfer pair, anomaly, duplicate, consistency check, match score) expose a plain-language explanation through an accessible `InfoHint` affordance',
            # was AC22.5.5
            test="apps/frontend/src/__tests__/infoHint.test.tsx::AC22.5.5 exposes the plain-language glossary text to assistive tech",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.12",
            statement='The reconciliation match-rate is shown under a single term ("Reconciliation coverage") on both Home and Reports, backed by one shared `InfoHint` glossary entry',
            # was AC22.9.2
            test="apps/frontend/src/__tests__/infoHint.test.tsx::AC22.9.2 exposes a single reconciliation-coverage term for the unified label",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.13",
            statement="Global styles honor `prefers-reduced-motion: reduce` by disabling non-essential animation/transition timing and smooth scrolling across the app shell",
            # was AC22.12.1
            test="apps/frontend/src/__tests__/designTokens.test.tsx::AC22.12.1 AC22.12.3 AC22.13.3 defines the global accessibility baseline in SSOT and CSS",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.14",
            statement="The authenticated shell exposes a skip-to-content link that targets the main landmark so keyboard users can bypass navigation chrome",
            # was AC22.12.2
            test="apps/frontend/src/__tests__/shellAndAuth.test.tsx::AC22.12.2 exposes a skip-to-content link targeting the main landmark",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.15",
            statement="Global focus-visible styles cover links, form controls, and shared `.btn-*` controls with token-backed focus rings",
            # was AC22.12.3
            test="apps/frontend/src/__tests__/designTokens.test.tsx::AC22.12.1 AC22.12.3 AC22.13.3 defines the global accessibility baseline in SSOT and CSS",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.16",
            statement="Shared toast and flow-step status affordances use Lucide icons or text instead of unicode glyph icons, and warning toast messages do not embed emoji-like status glyphs",
            # was AC22.12.5
            test="apps/frontend/src/__tests__/toastProviderComponent.test.tsx::AC22.12.5 uses semantic icon components instead of unicode glyph icons",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.17",
            statement="Data-dense report and asset-table loading states reserve layout with token-backed skeleton placeholders instead of spinner-only or text-only states",
            # was AC22.12.6
            test="apps/frontend/src/__tests__/uiPrimitives.test.tsx::AC22.12.6 renders token-backed skeleton primitives without spinner affordances",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.18",
            statement="Carryover accessibility review fixes keep the skip-link target covered by global focus-visible styling and keep report package table-of-contents section status in the accessible link name",
            # was AC22.13.3
            test="apps/frontend/src/__tests__/designTokens.test.tsx::AC22.12.1 AC22.12.3 AC22.13.3 defines the global accessibility baseline in SSOT and CSS",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.19",
            statement="A typed `patchUserSettings` client function in `lib/api.ts` issues `PATCH /api/users/me/settings` through the shared `apiFetch` client (no raw `fetch`) and returns the effective `UserAiSettings` response",
            # was AC22.15.1
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC22.15.1 fetchUserSettings GETs /api/users/me/settings via apiFetch",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.20",
            statement="The legacy `/events` alias is removed from `ROUTE_CONFIG` so `/notifications` is the single canonical path/label; the `/events`→`/notifications` redirect is unchanged",
            # was AC22.18.1
            test="apps/frontend/src/__tests__/navigation.test.ts::AC22.18.1 drops the legacy /events alias so /notifications is the one canonical label",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.21",
            statement="Balance sheet, income statement, and cash-flow pages download CSV through the authenticated API wrapper (backend cash-flow CSV export half migrated as `AC-reporting.csv-export.1`)",
            # was AC5.17.1
            test="apps/frontend/src/__tests__/apiFunctions.test.ts::AC5.17.1 downloads authenticated CSV blobs and preserves the server filename",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.21",
            statement="The install manifest uses the canonical `/` app launch route, stable app identity, standalone display, and required 192/512/apple icon metadata without relying on the legacy `/dashboard` redirect",
            # was AC22.20.1
            test="apps/frontend/src/__tests__/pwaInstall.test.tsx::AC22.20.1 keeps install manifest on the canonical home-screen launch contract",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.22",
            statement="The shared install hook captures Android/Chromium `beforeinstallprompt`, suppresses the browser's automatic prompt until the app-level action, invokes `prompt()`, and records dismissals so business pages do not handle install events",
            # was AC22.20.2
            test="apps/frontend/src/__tests__/pwaInstall.test.tsx::AC22.20.2 captures Android beforeinstallprompt and invokes the deferred native prompt",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.23",
            statement="The global app-shell install prompt renders an Android install action when a deferred prompt is available and renders iOS Add to Home Screen guidance when the browser cannot provide a programmatic prompt",
            # was AC22.20.3
            test="apps/frontend/src/__tests__/pwaInstall.test.tsx::AC22.20.3 renders the Android install action from the global app-shell prompt",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.24",
            statement="Installed or standalone sessions hide the install prompt, and the app shell uses safe-area-aware standalone styling for home-screen launch without page-level changes",
            # was AC22.20.4
            test="apps/frontend/src/__tests__/pwaInstall.test.tsx::AC22.20.4 detects iOS and standalone launch states without page code",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.25",
            statement="The navigation model exposes a bottom tab bar of Home (`/`), Chat (`/chat`), Audit (`/audit`), and More (`/more`) plus a center Add action, and no longer exposes a `primaryWorkflowNavItems`/`advancedNavItems` split or any of Journal/Reconciliation/Processing/Confidence/Accounts/Settings as a navigation entry",
            # was AC22.21.1
            test="apps/frontend/src/__tests__/navigation.test.ts::AC19.6.2 AC19.8.5 AC22.1.1 AC22.1.7 AC22.2.4 AC22.21.1 exposes a five-target bottom tab bar with distinct icons (Home, Chat, Add, Audit, More)",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.26",
            statement='The shell renders the bottom tab bar on mobile and mirrors the same five targets in the desktop sidebar; tapping Add opens a bottom sheet offering "Upload statement" (the statement uploader) and "Manual entry" (the guided evidence form), and Add is an action, not a route',
            # was AC22.21.2
            test="apps/frontend/src/__tests__/sidebarAndTabs.test.tsx::AC16.19.3 AC22.21.2 shows auth-aware sidebar actions mirroring the bottom tabs",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.27",
            statement="`/audit` renders a verify-on-demand hub aggregating Trust (confidence), Reconciliation, Journal, and Processing as cards that deep-link to their existing pages, and those pages render a back-link to `/audit`",
            # was AC22.21.3
            test="apps/frontend/src/__tests__/navigation.test.ts::AC22.21.3 folds the accounting machinery into the /audit hub, out of navigation",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.28",
            statement="`/settings` renders one page with General, AI, and LLM as tabs, and `/settings/general`, `/settings/ai`, `/settings/llm` resolve to that page with the corresponding tab active",
            # was AC22.21.4
            test="apps/frontend/src/__tests__/nextConfigRedirects.test.ts::AC22.21.4 redirects the legacy settings pages to the merged tabbed /settings",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.29",
            statement="`/more` lists low-frequency destinations — Portfolio (shown only when the user holds securities), Settings, Advanced, and Logout",
            # was AC22.21.5
            test="apps/frontend/src/__tests__/navigation.test.ts::AC22.21.5 routes low-frequency destinations through the /more overflow",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-ia-nav.30",
            statement="Desktop and mobile smoke covers the bottom tab bar, the Add sheet, the Audit hub, and the merged Settings without layout overflow, with safe-area-aware bottom-bar styling for standalone PWA sessions",
            # was AC22.21.7
            test="apps/frontend/playwright/epic022-bottom-tab-ia.spec.ts::the bottom bar opens the Add sheet with both ways to add",
            priority="P1",
            status="done",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from the
        # remaining EPIC files (EPIC-001/002/004/008/011/012/015/017/018/019/021/024/025) ──
        ACRecord(
            id="AC-meta.fe-http-client.1",
            statement="Frontend `apiFetch` throws `ApiError` carrying the parsed `errorId`",
            # was AC12.27.3
            test="apps/frontend/src/__tests__/apiErrorStructured.test.ts::test_AC12_27_3_api_error_carries_error_id parses error_id from the body",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-app-shell2.1",
            statement="`<ConfidenceBadge />` component renders `TRUSTED` / `HIGH` / `MEDIUM` / `LOW` pill with consistent color tokens (green / blue / amber / gray) and tooltip explaining source-type priority",
            # was AC18.5.1
            test="apps/frontend/src/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx::AC18.5.1 — ConfidenceBadge renders confidence tier labels",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-contract-types.1",
            statement="The list-response envelope has a single `ListResponse<T>` definition and the per-entity list responses derive from it; declared OpenAPI-mirrored contract types resolve to a real generated `Schemas[...]` key (drift guard)",
            # was AC25.3.1
            test="apps/frontend/src/__tests__/contractTypes.test.ts::AC25.3.1: every list response derives from the single ListResponse<T> envelope",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-http-client.2",
            statement="High-traffic call sites type responses against the generated schema",
            # was AC12.28.3
            test="apps/frontend/src/__tests__/apiTypedClient.test.ts::test_AC12_28_3_types_stage2_batch_responses_against_generated_schema",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-contract-types.2",
            statement="`lib/api.ts` is the single raw-`fetch` boundary — no other frontend source module issues a raw `fetch(` call",
            # was AC25.3.2
            test="apps/frontend/src/__tests__/contractTypes.test.ts::AC25.3.2: lib/api.ts is the single raw-fetch boundary in the frontend",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-contract-types.3",
            statement=(
                "No component-local `interface FooResponse`/`interface FooRequest` "
                "wire-shape declarations exist outside `lib/` — every wire type "
                'either resolves to a generated `Schemas["..."]` alias or is a '
                "justified hand type documented in `lib/types.ts` (#1868 S5: 7 "
                "such interfaces across 6 component files silently duplicated, "
                "and in one case drifted from, the generated contract)."
            ),
            test=(
                "tests/tooling/test_fe_wire_type_ssot.py"
                "::test_AC_fe_wire_ssot_1_no_hand_declared_response_request_outside_lib"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-contract-types.4",
            statement=(
                "`countLabel`/`pnlColorClass`/`formatPeriod`/`isActive`/"
                "`readinessVariant` each have at most one definition, at one "
                "canonical home (`lib/statusLabels.ts`, `lib/date.ts`, "
                "`components/navigation.ts`) — were 2-3 component-local copies "
                'each, with `formatPeriod` already diverged (a "→" vs "to" '
                "separator) and `readinessVariant` already diverged (its two "
                'definitions\' "unhandled"/default branches assigned '
                "conflicting Badge colors — the two source enums don't "
                "actually overlap on which states hit that default) before "
                "unification. The gate actively governs the renamed name too "
                "(`pnlColorClass`, "
                "not just banning the old `getPnlColor`), so a future duplicate "
                "of the CURRENT name is caught, not only a regression to the "
                "old one. `formatCurrency` is defined only in "
                "`lib/audit/money/format.ts` (amount formatting) — no second "
                "definition colliding in name with a currency-CODE formatter "
                "exists anywhere else (#1868 S5)."
            ),
            test=(
                "tests/tooling/test_fe_helper_ssot.py"
                "::test_AC_fe_helper_ssot_1_each_helper_defined_at_most_once"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-meta.fe-contract-types.5",
            statement=(
                "No file under `apps/frontend/src/components/workflow/` exceeds "
                "300 lines, and `cx` has exactly one definition in the tree "
                "(exported from `components/ui`) — `WorkflowNotifications.tsx` "
                "was a 769-line god-file with a private re-implementation of "
                "`cx` that already existed, unexported, in `components/ui/index.tsx` "
                "(#1868 S5 PR-C). Split into one component per file, re-exported "
                "as a barrel from the original path so external imports are unchanged."
            ),
            test=(
                "tests/tooling/test_fe_no_godfile.py"
                "::test_AC_fe_no_godfile_1_workflow_files_stay_under_300_lines"
            ),
            priority="P2",
            status="done",
        ),
    ],
    concepts=[
        ConceptRecord(
            key="api_surface_terminal_home",
            owner="common/meta/contract.py",
            description=(
                "The terminal home for HTTP adapters is the owning package's "
                "extension/api/ layer; src/routers is transitional and may only "
                "shrink (#1865 S2)."
            ),
            cross_refs=[
                "common/testing/api_surface_ratchet.py",
                "common/testing/data/api-surface-ratchet-baseline.json",
                "tests/tooling/test_api_surface_ratchet.py",
            ],
            proofs=["tests/tooling/test_api_surface_ratchet.py"],
            family="platform",
            kind="concept",
            authority="documented_contract",
            parent="package_model",
        ),
        ConceptRecord(
            key="ac_tier_baseline",
            owner="common/meta/data/ac-tier-baseline.json",
            description=(
                "Shrink-only untagged-AC debt baseline for the authority-tier ratchet "
                "(tools/check_ac_tier_baseline.py); lists ACs that predate the tier attribute "
                "and may stay untagged, so new/changed ACs must declare a tier while legacy "
                "debt ratchets down."
            ),
            cross_refs=[
                "common/meta/readme.md",
                "common/meta/extension/check_ac_tier_baseline.py",
                "tools/check_ac_tier_baseline.py",
                "tests/tooling/test_ac_authority_tiers.py",
            ],
            family="tdd",
            kind="baseline",
            authority="machine_generated",
            parent="authority_tiers",
        ),
        ConceptRecord(
            key="app_boundary_baseline",
            owner="common/meta/data/app-boundary-baseline.json",
            description=(
                "Monotonic shrink-only baseline of cross-boundary edges between the un-carved "
                "apps/backend/src remainder (the L4 backend super-package) and the "
                "already-carved packages — inbound (remainder → a carved package's "
                "unpublished internal) and outbound (a carved package → the app remainder, "
                "upward-layer). A new edge fails check_app_boundary; the count is the "
                "migration burndown."
            ),
            cross_refs=[
                "common/meta/migration-standard.md",
                "common/meta/extension/app_boundary.py",
                "common/meta/extension/check_app_boundary.py",
                "tools/check_app_boundary.py",
                "tests/tooling/test_app_boundary.py",
            ],
            family="platform",
            kind="baseline",
            authority="machine_generated",
            parent="package_model",
        ),
        ConceptRecord(
            key="authority_tiers",
            owner="common/meta/readme.md",
            description=(
                "The five AC authority tiers (CODE-ONLY/CODE-LED/HU/LLM-LED/LLM-ONLY), the "
                "cross-tier MUST rules, and the tier->valid-proof matrix; one AC = one tier, "
                "declared via a {tier:XX} marker at the AC definition site and ratcheted by a "
                "shrink-only untagged-debt baseline. Internalized into the authority package "
                "(migration-standard step 3); the central docs/ssot/authority-tiers.md is "
                "retired."
            ),
            cross_refs=[
                "common/testing/tdd.md",
                "common/llm/ai.md",
                "common/extraction/readme.md",
                "docs/project/EPIC-026.ac-authority-tiers.md",
                "common/meta/data/ac-tier-baseline.json",
                "common/meta/extension/generate_ac_registry.py",
                "common/meta/base/authority_matrix.py",
                "common/meta/extension/check_ac_tier_baseline.py",
                "tools/check_ac_tier_baseline.py",
                "common/meta/extension/check_tier_ast_literal.py",
                "common/meta/extension/check_epic_package_dual.py",
                "common/meta/extension/check_draft_packages.py",
                "common/meta/extension/authority_classifier.py",
                "common/meta/extension/check_authority_reconcile.py",
            ],
            proofs=["tests/tooling/test_ac_authority_tiers.py"],
            family="tdd",
            kind="concept",
            authority="documented_contract",
            parent="tdd_workflow",
        ),
        ConceptRecord(
            key="ci_gate_inventory",
            owner="common/meta/data/ci-gate-inventory.yaml",
            description=(
                "Transitional workflow-job inventory mapping current gates to proof stage and "
                "task_category, plus finish fan-in ownership and duplicate cleanup "
                "candidates."
            ),
            cross_refs=[
                "common/testing/ci-cd.md",
                "docs/project/EPIC-008.testing-strategy.md",
                ".github/workflows/ci.yml",
            ],
            proofs=["tests/tooling/test_ci_gate_inventory.py"],
            family="delivery",
            kind="matrix",
            authority="human_curated",
            parent="ci_workflow",
        ),
        ConceptRecord(
            key="data_layering",
            owner="common/meta/schema.md#data-layering",
            description=(
                "ODS/DWD/DWM/DWS/ADS/DIM classification of every data table and cross-layer "
                "rules."
            ),
            cross_refs=[
                "common/extraction/readme.md",
                "common/reconciliation/reconciliation.md",
                "docs/project/EPIC-011.asset-lifecycle.md",
            ],
            family="schema",
        ),
        ConceptRecord(
            key="database_schema",
            owner="common/meta/schema.md#er-model",
            description=(
                "PostgreSQL schema rationale, generated inventory reference, and migration "
                "rules."
            ),
            cross_refs=[
                "docs/reference/api-overview.md",
                "docs/hooks.py",
                "tools/generate_db_schema_reference.py",
                "common/meta/extension/generate_db_schema_reference.py",
                "common/ledger/readme.md",
                "common/reconciliation/reconciliation.md",
            ],
            proofs=[
                "tests/tooling/test_generate_db_schema_reference.py",
                "apps/backend/tests/infra/test_schema_guardrails.py",
            ],
            family="schema",
            kind="concept",
            authority="documented_contract",
        ),
        ConceptRecord(
            key="delivery_gate_triggers",
            owner="common/meta/data/delivery-gates.yaml",
            description=(
                "How each delivery CI gate triggers and whether it blocks merge — the single "
                "source for trigger/blocking contracts (so a trigger change is one edit, not "
                "a fact restated across docs/tests)."
            ),
            cross_refs=[
                "common/testing/ci-cd.md",
                "common/runtime/environments.md",
                "docs/project/EPIC-008.testing-strategy.md",
                ".github/workflows/preview.yml",
                ".github/workflows/deploy.yml",
                ".github/workflows/deploy.yml",
            ],
            proofs=["tests/tooling/test_delivery_gates_contract.py"],
            family="delivery",
            kind="matrix",
        ),
        ConceptRecord(
            key="delivery_layer_baseline",
            owner="common/meta/data/delivery-layer-baseline.json",
            description=(
                "Thin-ness ratchet census of the sanctioned app delivery layer — "
                "per-directory *.py line totals of apps/backend/src/routers (HTTP delivery "
                "adapters) and apps/backend/src/schemas (API DTOs), which are hexagonal "
                "primary adapters, not domain behavior (#1763 ruling); CI enforces the census "
                "stays within a 50-line band of the baseline, so silent growth fails and "
                "growing the delivery layer requires a same-PR baseline edit (reviewable "
                "consent), while meaningful shrink lowers the baseline in the same PR to keep "
                "the ratchet tight; the delivery layer's bulk may only shrink as packages "
                "absorb logic (AC-meta.delivery.1)."
            ),
            cross_refs=[
                "tests/tooling/test_delivery_layer_ratchet.py",
                "common/meta/migration-standard.md",
            ],
            family="platform",
            kind="baseline",
            authority="machine_generated",
            parent="package_model",
        ),
        ConceptRecord(
            key="draft_package_baseline",
            owner="common/meta/data/draft-package-baseline.json",
            description=(
                "Registered draft packages for the migration-safety draft gate "
                "(tools/check_draft_packages.py); a draft package leaves its authority tier "
                "undecided, so listing it here makes adding one a reviewed act and a draft "
                "must carry no done ACs."
            ),
            cross_refs=[
                "common/meta/readme.md",
                "common/meta/extension/check_draft_packages.py",
                "tools/check_draft_packages.py",
                "tests/tooling/test_migration_safety_gates.py",
            ],
            family="tdd",
            kind="baseline",
            authority="machine_generated",
            parent="authority_tiers",
        ),
        ConceptRecord(
            key="enum_naming",
            owner="common/meta/schema.md#enum-naming",
            description="All sa.Enum instances MUST have an explicit name parameter.",
            cross_refs=[
                "AGENTS.md",
                "docs/agents/red-lines.md",
                "apps/backend/tests/infra/test_schema_guardrails.py",
            ],
            family="schema",
        ),
        ConceptRecord(
            key="environment_variables",
            owner="common/meta/development.md#environment-variables",
            description="App env SSOT generated from config.py into .env.example and required-env manifest.",
            cross_refs=[
                "docs/agents/red-lines.md",
                "common/runtime/deployment.md",
                ".env.example",
                "apps/backend/src/config.py",
                "common/runtime/required-env.generated.json",
                "apps/backend/src/runtime/extension/env_keys.py",
                "apps/backend/src/runtime/extension/schema_validation.py",
                "tools/check_env_keys.py",
                "tools/validate_schemas.py",
                "tools/generate_env_reference.py",
                ".pre-commit-config.yaml",
            ],
            family="development",
        ),
        ConceptRecord(
            key="epic_residue_baseline",
            owner="common/meta/data/epic-residue-baseline.json",
            description=(
                "Ratchet census of the post-migration EPIC residue (#1719) - per "
                "docs/project/EPIC-*.md file, the count of AC definition lines per explicit "
                "residue category (fe-only / fe-half / horizontal / pending-package, single "
                "vocabulary source common/meta/extension/generate_ac_registry.py "
                "EPIC_RESIDUE_CATEGORIES); CI enforces unmarked EPIC AC rows == 0 (the "
                "umbrella scoreboard metric), census == baseline so residue growth is a "
                "same-PR reviewable baseline edit, a shrink-only EPIC file set, and an "
                "explicit design-doc/goal-stub justification on every zero-row EPIC file "
                "(AC-meta.residue.1)."
            ),
            cross_refs=[
                "tests/tooling/test_epic_residue_ratchet.py",
                "common/meta/extension/generate_ac_registry.py",
                "common/meta/migration-standard.md",
            ],
            family="platform",
            kind="baseline",
            authority="machine_generated",
            parent="package_model",
        ),
        ConceptRecord(
            key="fk_cascade_baseline",
            owner="common/meta/data/fk-cascade-baseline.json",
            description=(
                'Ratchet census of ForeignKey(..., ondelete="CASCADE") sites under '
                "apps/backend/src, keyed by target table — a DB cascade is a hidden write "
                "below the application (across domains it breaks one-txn-per-domain and "
                "append-only, the risk the ratchet exists for); CI enforces census == "
                "baseline, so silent growth fails and adding a cascade requires a same-PR "
                "baseline edit (reviewable consent); deliberately counts all sites, not just "
                "cross-domain, until models decentralization makes ownership derivable; "
                "end-state is saga-owned deletion (AC-meta.txn.4, #1675 ruling)."
            ),
            cross_refs=[
                "tests/tooling/test_fk_cascade_ratchet.py",
                "common/meta/migration-standard.md",
            ],
            family="platform",
            kind="baseline",
            authority="machine_generated",
            parent="package_model",
        ),
        ConceptRecord(
            key="local_host_shells",
            owner="common/meta/development.md#local-host-shell-matrix",
            description=(
                "Supported local command shells and PATH/tool-install boundaries across WSL "
                "Ubuntu, macOS/Linux, Windows PowerShell, and Codex runner contexts."
            ),
            cross_refs=[
                "README.md",
                "common/runtime/environments.md#host-shell-boundaries",
                "tools/bootstrap.sh",
                "tools/_lib/shell/",
                "common/runtime/shell/common.sh",
            ],
            family="development",
        ),
        ConceptRecord(
            key="migration_risk_classification",
            owner="common/meta/data/migration-risk.yaml",
            description=(
                "Machine-readable risk level and release proof contract for Alembic "
                "migrations."
            ),
            cross_refs=[
                "common/meta/schema.md",
                "common/testing/ci-cd.md",
                "common/runtime/deployment.md",
                "tools/check_migration_risk.py",
                "common/meta/extension/migration_risk.py",
                "tests/tooling/test_migration_risk_contract.py",
            ],
        ),
        ConceptRecord(
            key="moon_commands",
            owner="common/meta/development.md#moon-commands",
            description="Primary interface for dev, lint, test, and build tasks.",
            cross_refs=["AGENTS.md", "docs/contributing/branch-policy.md"],
            family="development",
        ),
        ConceptRecord(
            key="namespace_isolation",
            owner="common/meta/development.md#local-test-isolation",
            description="Namespace-based test DB and S3 bucket isolation for parallel runs.",
            cross_refs=["common/runtime/environments.md"],
            family="development",
        ),
        ConceptRecord(
            key="package_model",
            owner="common/meta/readme.md#package-model",
            description=(
                "A package = a DDD bounded context (readme.md + PackageContract + "
                "base/extension/data layers carrying DDD building-block units + __all__ "
                "published language); placement resolved from the central five-layer map "
                "`PACKAGE_LAYER` (`meta < infra < middleware < domain < app`; defined in "
                "`common/meta/base/layering.py`); governance is computed from contracts by "
                "check_package_contract. The model self-hosts in the common/meta package "
                "(base = model, extension = gate, data = projection)."
            ),
            cross_refs=[
                "common/meta/base/package_contract.py",
                "common/meta/extension/check_package_contract.py",
                "common/meta/data/projection.py",
                "common/meta/contract.py",
                "common/counter/readme.md",
                "common/counter/contract.py",
                "apps/backend/src/counter/__init__.py",
                "common/identity/readme.md",
                "common/identity/contract.py",
                "apps/backend/src/identity/__init__.py",
                "common/ledger/contract.py",
                "docs/project/EPIC-025.dry-ssot-simplification.md",
            ],
            proofs=["tests/tooling/test_counter_package.py"],
            family="platform",
            kind="concept",
            authority="documented_contract",
        ),
        ConceptRecord(
            key="runtime_toolchain",
            owner="common/meta/development.md#toolchain-contract",
            description=(
                "Python, Node.js, uv, and container image versions shared by local, CI, and "
                "Docker environments."
            ),
            cross_refs=[
                "toolchain.toml",
                "tools/bootstrap.sh",
                "tools/_lib/shell/bootstrap.sh",
                "common/runtime/shell/common.sh",
                "tools/check_toolchain_contract.py",
                "common/runtime/check_toolchain_contract.py",
                ".moon/toolchain.yml",
                ".github/workflows/ci.yml",
                "docker-compose.yml",
                "docker-compose.pr-preview.yml",
            ],
        ),
        ConceptRecord(
            key="ssot_governance_exceptions",
            owner="common/meta/data/governance-exceptions.yaml",
            description=(
                "Machine-readable temporary exception registry for incremental SSOT "
                "governance gate findings."
            ),
            cross_refs=[
                "common/testing/tdd.md",
                "common/meta/extension/governance_report/_gate.py",
                "tests/tooling/test_ssot_governance_report.py",
            ],
            family="tdd",
            kind="registry",
            parent="ssot_governance_gates",
        ),
    ],
)

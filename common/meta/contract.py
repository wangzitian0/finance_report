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
            statement="check_env_keys.py exits non-zero on a secret/config/env three-way drift. Was AC14.1.4.",
            test="tests/tooling/test_issue_493_foundation_ttd_behavior.py::test_AC14_1_4_check_env_keys_exits_nonzero_for_secret_config_drift",
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
            statement="SSOT governance metrics report finance_report and infra2 manifest shape, proof coverage, and future gate candidates without blocking CI. Was AC14.1.12.",
            test="tests/tooling/test_ssot_governance_report.py::test_AC14_1_12_report_covers_finance_and_infra2_manifest_shapes",
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
            statement="A single parseable vision-to-proof matrix is mechanically generated from vision.md anchors, EPIC Vision Anchor declarations, the AC registries, and test references, and --check fails on drift. Was AC14.1.19.",
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
                "The staging/prod deploy compose (infra2 10.app/compose.yaml) "
                "cannot local-build the app services (no build:, "
                "pull_policy: always)."
            ),
            test=(
                "tests/tooling/test_deploy_compose_contract.py"
                "::test_AC7_12_3_deploy_compose_pull_not_build"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.infra-boundary.2",
            statement=(
                "The postgres/redis data dirs are bind-mounted via "
                "${DATA_PATH} (not a named volume Dokploy wipes on redeploy)."
            ),
            test=(
                "tests/tooling/test_deploy_compose_contract.py"
                "::test_AC7_12_3_data_dirs_survive_redeploy"
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
                "equal docs/ssot/epic-residue-baseline.json (the fk-cascade "
                "idiom): silent residue growth fails CI and adding residue "
                "requires raising the baseline in the same PR, where the "
                "diff makes the choice reviewable; the EPIC file set may "
                "only shrink (a new EPIC file fails; a deleted one must "
                "prune the baseline); an EPIC file with zero marked rows "
                "must carry an explicit <!-- epic-file: design-doc|"
                "goal-stub --> justification. The registry generator feeds "
                "the AC registry from marked rows only, so an unmarked row "
                "is invisible to the registry AND fails the gate."
            ),
            test=(
                "tests/tooling/test_epic_residue_ratchet.py"
                "::test_AC_meta_residue_1_census_equals_baseline_and_files_only_shrink"
            ),
            priority="P0",
            status="done",
        ),
        # ── manifest: docs/ssot/MANIFEST.yaml stays hand-authored (a full
        # computed concept index is a follow-up, #1799), but every file it
        # governs must be explicitly classified — anti-drift in the same
        # spirit as the residue markers above (#1664 "retire the center",
        # Part C). ──
        ACRecord(
            id="AC-meta.manifest.1",
            statement=(
                "Every file physically present in docs/ssot/ is referenced "
                "by name in docs/ssot/README.md — the pointer page "
                "classifying each surviving file as cross-cutting infra "
                "(Cross-Cutting Classification table), live gate data (Gate "
                "Data Directory section), a generated artifact, or a "
                "migrated pointer stub. A file dropped into docs/ssot/ "
                "without a matching README entry is silent, unclassified "
                "drift and fails CI. This stands in for the full computed "
                "concept-ownership index (no `concepts` field exists on "
                "PackageContract yet to project from — see docs/ssot/"
                "README.md § 'MANIFEST.yaml Status' and follow-up #1799) "
                "without forcing that larger rewrite under time pressure."
            ),
            test=(
                "tests/tooling/test_check_manifest.py"
                "::test_AC_meta_manifest_1_real_docs_ssot_is_fully_classified"
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
    ],
)

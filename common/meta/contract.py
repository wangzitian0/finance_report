"""Machine-checkable PackageContract for ``meta``."""

from __future__ import annotations

from common.meta.package_contract import (
    ContextScope,
    GovernanceGuarantee,
    GovernanceInitiative,
    PackageContract,
    acs,
    concepts,
    invs,
    units,
)

CONTRACT = PackageContract(
    name="meta",
    status="active",
    tier="CODE-ONLY",
    depends_on=[],
    roles="base extension data".split(),
    implementations={"be": "common/meta", "fe": None},
    context=ContextScope(
        purpose="Define the package-governance language and compute the validations, indexes.",
        in_scope=[
            "Package-contract vocabulary and topology.",
            "Computed package governance indexes and reports.",
            "Contract and SSOT validation gates.",
        ],
        out_of_scope=[
            "Individual package business goals and domain policy.",
            "Product direction and prioritization.",
            "Runtime delivery and application composition.",
        ],
    ),
    units=units(
        """
PackageContract|agg|base/package_contract.py
@vo|base/package_contract.py|ACRecord Invariant Kind
@vo|base/governance_control.py|GovernanceGuarantee GovernanceInitiative
@vo|base/dependency_graph.py|DependencyKind DependencyEdge
check_package_contract|svc|extension/check_package_contract.py
@proj|data/projection.py|contract_index ac_vision_index dependency_index
Unit|vo|base/package_contract.py|-|package-unit
"""
    ),
    interface="""
ACRecord CommandBoundary ConceptRecord DependencyEdge DependencyKind
GovernanceGuarantee GovernanceInitiative Invariant Kind PackageContract Unit
ac_vision_index concept_index contract_index dependency_index
""".split(),
    events=[],
    invariants=invs(
        """
@$t/test_check_package_contract.py
contract-equals-published-language|A package's contract.interface must equal its BE implementation's __init__.__all__.|test_interface_mismatch_is_reported
public-function-has-single-package-owner|A snake_case public function name may be exported by exactly one package contract.|test_duplicate_public_function_exports_are_rejected
unproven-reference-is-rejected|Every invariants[].test and roadmap[].test must resolve to a real test function.|test_unresolved_invariant_and_roadmap_refs_are_reported
dag-down-only|A package's implementation may import only strictly-lower-class packages declared in depends_on.|test_upward_edge_is_forbidden
active-package-has-a-decided-tier|Authority tier is a module-design property declared once on the PackageContract.|test_active_package_must_declare_a_tier
ac-proof-kind-satisfies-package-tier-matrix|Every roadmap AC's proof_kind must be valid for the package's tier per the single machine matrix.|test_package_proof_kind_must_satisfy_the_tier_matrix
@$t/test_meta_layering.py
meta-converges-by-layer|The meta package converges into base/ + extension/ + data/.|test_meta_converges_by_layer
meta-base-is-pure|The meta base/ layer never imports its own extension/ or data/.|test_meta_base_is_pure
@-
every-common-directory-is-governed-or-excepted|Check_package_contract discovers packages additively (globs common/*/contract.py for a module-level CONTRACT = PackageContract).|$t/test_check_package_directory_coverage.py::test_contract_file_without_exported_contract_is_rejected
one-vocabulary-two-views|The detected band scale IS the declared tier scale.|$t/test_authority_classifier.py::test_AC26_9_1_band_boundaries
declared-reconciles-with-detected|A shipped package's declared tier agrees with its detected CODE/LLM band at the enforceable ends.|$t/test_migration_safety_gates.py::test_reconcile_flags_llm_test_under_code_only
"""
    ),
    roadmap=acs(
        "meta",
        """
@$t/test_meta_layering.py|P0
kind.1|A declared unit must live in the layer its kind dictates.|test_AC_meta_kind_1_unit_misplacement_is_rejected
kind.2|A repository unit must split into a base port + an extension adapter.|test_AC_meta_kind_2_repository_requires_port_and_adapter
kind.3|The data/ layer is a sink.|test_AC_meta_kind_3_data_layer_is_a_sink|P1
projection.1|Contract_index is a pure projection over the contracts it is handed.|test_AC_meta_projection_1_contract_index_is_pure|P1
vision-anchor.1|A package-roadmap AC may declare one vision.md anchor.|test_AC_meta_vision_anchor_1_projection_is_pure|P1
kind.4|A value-type package may declare value-object units for the taxonomy.|test_AC_meta_kind_4_value_type_packages_pass|P2
txn.1|A base unit reaching into another registered domain's unpublished object is rejected.|test_AC_meta_txn_1_base_deep_import_of_other_domain_object_is_rejected
txn.2|A domain's extension reaching into another domain's ORM/models is rejected.|test_AC_meta_txn_2_extension_writing_other_domain_orm_is_rejected
txn.3|A SQLAlchemy relationship whose target model belongs to another registered domain is rejected.|test_AC_meta_txn_3_cross_domain_relationship_is_rejected_fk_column_is_allowed|P1
@$t/test_check_package_contract.py|P0
public-boundary.2|A declared command boundary resolves to exactly one definition in its package implementation.|test_AC_meta_public_boundary_2_command_boundary_rejects_dynamic_types
package-truth.1|Every discovered package has the two authored truth surfaces readme.md and contract.py.|test_AC_meta_package_truth_1_authored_surface_is_exact_and_non_vacuous
@$t/test_generate_vision_proof_matrix.py|P0
vision-anchor.2|The vision proof matrix includes package-roadmap ACs under their declared vision anchors and rejects any anchor absent from vision.md.|test_AC_meta_vision_anchor_2_package_ac_backs_vision_node
generated-refs.2|The vision-to-proof matrix is built in memory from vision.md anchors, EPIC ownership declarations, package-roadmap vision_anchor declarations, the AC registries.|test_AC14_1_19_matrix_maps_vision_to_ac_to_test|P1
@$t/test_five_layer_model.py|P0
layer.1|The package topology is the five ordered layers meta < infra < middleware < domain < app.|test_old_klass_vocabulary_is_rejected
layer.2|Placement is resolved from the central PACKAGE_LAYER map.|test_declared_klass_must_match_central_map
layer.3|No declared depends_on edge points to a higher layer.|test_no_depends_on_edge_points_to_a_higher_layer
layer.4|The L0 vocabulary modules stay importable.|test_layer_vocabulary_imports_without_pydantic|P1
layer.5|Common/meta/readme.md links the generated five-layer topology from PACKAGE_LAYER and contains no hand-authored diagram.|test_readme_links_the_generated_five_layer_topology|P2
@$t/test_ac_authority_tiers.py|P0
AC-authority.1.1|Common/meta/readme.md is the single registered owner of the tier vocabulary, the cross-tier MUST rules.|test_AC26_1_1_ssot_defines_five_tiers_and_proof_matrix
AC-authority.2.1|A {tier:XX} marker at an AC's definition site flows tier into its registry value.|test_AC26_2_1_tier_marker_flows_into_registry_value
AC-authority.3.1|The tier ratchet is shrink-only.|test_AC26_3_1_tier_ratchet_is_shrink_only_and_blocks_new_debt
AC-authority.4.1|The first-batch EPICs are fully tier-tagged and off the untagged-debt baseline.|test_AC26_4_1_first_batch_epics_fully_tagged_and_off_baseline
@$t/test_ac_proof_kind.py|P0|done|property
AC-authority.5.1|A {proof:KIND} marker flows into the registry as proof_kind.|test_AC26_5_1_proof_kind_marker_flows_and_gate_enforces_matrix
AC-authority.6.1|The first-batch LLM-LED/HU/LLM-ONLY ACs each declare a matrix-valid proof_kind.|test_AC26_6_1_first_batch_lp_acs_carry_invariant_proof
@$t/test_issue_493_foundation_ttd_behavior.py|P0
foundation-tooling.1|Backend coverage threshold is enforced locally.|test_AC14_1_1_backend_pyproject_enforces_local_coverage_threshold
foundation-tooling.2|The pre-commit mypy hook runs against apps/backend/src and blocks type errors.|test_AC14_1_2_pre_commit_mypy_hook_blocks_backend_type_errors
foundation-tooling.3|Validate_schemas.py checks only changed schema paths in pre-commit and exits non-zero.|test_AC14_1_3_validate_schemas_exits_nonzero_for_missing_field_descriptions
foundation-tooling.4|Check_env_keys.py exits non-zero on config/.env.example drift.|test_AC14_1_4_check_env_keys_exits_nonzero_for_config_documentation_drift
foundation-tooling.5|Smoke_test.sh succeeds against a mocked local environment.|test_AC14_1_5_smoke_test_succeeds_against_mocked_local_environment|P1
registry.1|Generate_ac_registry.py produces zero ghost ACs and zero id overlap between the feature and infra registries.|test_AC14_1_6_generate_ac_registry_check_rejects_ghosts_and_keeps_no_overlap|P1
@$t/test_lint_doc_consistency.py|P0
doc-consistency.1|Generated analysis snapshots are not checked into docs/project/.|test_AC14_1_7_generated_analysis_snapshots_are_absent
doc-consistency.2|Reconciliation threshold prose points to its code/config owner.|test_AC14_1_8_reconciliation_thresholds_are_code_owned
doc-consistency.3|Frontend source cannot call raw fetch outside apps/frontend/src/lib/api.ts.|test_AC14_1_10_frontend_raw_fetch_is_limited_to_api_wrapper
@$t/test_check_manifest.py|P2
ssot-governance.1|SSOT manifest #anchor owners and cross-references resolve to actual Markdown anchors.|test_AC14_1_9_manifest_anchor_refs_must_exist|P0
manifest.1|The residual concept-ownership registry lives at common/meta/data/MANIFEST.yaml.|test_AC_meta_manifest_1_manifest_relocated_and_ssot_retired
manifest.2|Check_manifest.py validates the computed UNION of the residual MANIFEST.yaml and every package's own `concepts=[ConceptRecord, ...]` declaration.|test_AC_meta_manifest_2_concept_from_package_contract_is_validated
@$t/test_ssot_governance_report.py|P1
ssot-governance.2|SSOT governance metrics report Finance Report manifest shape, proof coverage.|test_AC14_1_12_report_covers_finance_manifest_shape
ssot-governance.3|SSOT governance gates block changed-file and changed-manifest-entry debt, explain #823/HLS ownership.|test_AC14_1_13_incremental_gate_only_blocks_changed_ssot_debt
ssot-governance.4|Threshold cleanup for #824 reduces finance_report.orphan_ssot_files to zero by binding orphan SSOT files to parent concepts.|test_AC14_1_14_finance_report_orphan_ssot_files_are_manifest_owned
ssot-governance.5|Threshold cleanup for #824 migrates representative machine-owned FR SSOT entries to explicit family/kind/proofs and inbound links.|test_AC14_1_15_machine_owned_ssot_entries_have_explicit_shape_and_proof
ssot-governance.6|SSOT governance gates keep protected per-system governance ratios non-decreasing and protected debt counts non-increasing against the base ref.|test_AC14_1_16_ssot_governance_ratios_cannot_regress
ssot-governance.8|Threshold cleanup for #824 reduces finance_report.high_risk_entries_missing_proof to zero by binding the flagged high-risk platform concepts to existing proof tests.|test_AC14_1_23_high_risk_ssot_entries_bind_proof_under_platform_family
ssot-governance.9|Incremental SSOT governance compares the same computed concept registry at base and HEAD, detects package-contract concept drift, isolates the requested git ref.|test_AC_meta_ssot_governance_9_base_and_head_use_same_computed_concepts|P0
@$t/test_coverage_artifact_preflight.py|P0
coverage-tiers.1|Unified coverage aggregation runs an artifact preflight that fails explicitly and names the offending component LCOV.|test_AC14_1_20_preflight_fails_when_ci_critical_artifact_missing
coverage-tiers.2|Coverage components carry an explicit tier.|test_AC14_1_21_tools_component_is_best_effort_tier|P1
@$t/test_migration_risk_contract.py|P0
migration-risk.1|Every backend Alembic migration is covered by a machine-readable migration risk manifest.|test_AC7_11_1_migration_risk_manifest_covers_backend_migrations
migration-risk.2|High and critical migration risk entries require release proof notes covering staging validation, production preflight.|test_AC7_11_2_high_and_critical_migrations_require_release_proof
migration-risk.3|A destructive upgrade operation cannot be classified below critical risk.|test_AC7_11_3_destructive_migrations_must_be_classified_critical
migration-risk.4|CI lint and the production release dry-run both execute the migration risk contract and publish its release context.|test_AC7_11_4_ci_and_release_dry_run_execute_migration_risk_contract
migration-risk.5|Risk is auto-classified from each migration's upgrade body.|test_AC7_11_5_low_and_medium_migrations_are_auto_classified
@$t/test_post_merge_e2e_gates.py|P0
release-pipeline.1|The production release workflow promotes the staging-validated `:<sha>` image to `vX.Y.Z`.|test_AC7_10_production_release_promotes_not_rebuilds|:property
infra-boundary.1|Finance Report declares runtime-hooks.manifest.json for infra2-sdk v3.24.0 and does not read or execute infra2 source.|test_AC_runtime_deploy_request_4_repository_has_no_infra2_source_edge
infra-boundary.2|Infra2 owns compose, data persistence, Vault injection.|test_AC_runtime_deploy_request_4_repository_has_no_infra2_source_edge
@$t/test_publish_only_contract.py|P1
infra-boundary.3|Ci.yml's on.push.branches only includes main and promote-release-images verifies origin/main ancestry on v* tag pushes.|test_AC7_12_4_release_branches_trigger_the_publish_workflow
infra-boundary.4|The container-image push.|test_AC7_12_4_image_push_publishes_for_main_release_and_dispatch
@$t/test_data_red_lines_contract.py|P1
infra-boundary.6|Environments.md defines the derived data-lane contract for deploy_v2.|test_AC7_12_6_environments_define_data_axis_and_red_lines
infra-boundary.7|The root SSOT does not drift back to the retired public-axis deploy primitive.|test_AC7_12_6_deploy_v2_data_lane_is_derived_not_public_axis
@$be/infra/test_epic_001_contracts.py|P1
phase0.1|Root moon.yml exists.|test_epic_001_moon_workspace_configs_exist
phase0.2|Apps/backend/moon.yml exists.|test_epic_001_moon_workspace_configs_exist
phase0.3|Apps/frontend/moon.yml exists.|test_epic_001_moon_workspace_configs_exist
phase0.4|Tools/smoke_test.sh environment verification command exists.|test_epic_001_moon_workspace_configs_exist
phase0.5|The FastAPI project structure exists (apps/backend skeleton).|test_epic_001_backend_skeleton_exists
phase0.7|Next.js App Router files exist.|test_epic_001_frontend_skeleton_exists
phase0.8|TailwindCSS configuration exists.|test_epic_001_frontend_skeleton_exists
phase0.10|TanStack Query dependency is configured.|test_epic_001_frontend_uses_react_query
phase0.12|PostgreSQL 15 container is defined in docker-compose.|test_epic_001_docker_compose_contract
phase0.13|Redis 7 container is defined in docker-compose.|test_epic_001_docker_compose_contract
phase0.14|Data volumes are configured in docker-compose.|test_epic_001_docker_compose_contract
phase0.16|The frontend startup command path is valid (Moon task configured).|test_epic_001_frontend_moon_tasks_configured
phase0.18|Pre-commit hooks configuration is present.|test_epic_001_pre_commit_config_exists
@$be/infra/test_ci_config.py|P1
phase0.11|Docker-compose.yml integrity is valid.|test_docker_compose_integrity
phase0.15|The Moon project graph contract is declared in repo config.|test_moon_project_graph_static_contract
phase0.19|The Moon local CLI contract is versioned.|test_moon_cli_static_contract_available
@$t/test_framework_reporting_epic_contract.py|P1
framework-neutrality.1|Canonical ledger documentation declares that double-entry posting is framework-neutral and that US/HK policy decisions belong to EPIC-020.|test_AC2_18_1_canonical_ledger_is_framework_neutral
framework-neutrality.2|Reporting docs declare that EPIC-005 consumes framework policy results for US/HK package output and does not own framework-specific accounting decisions.|test_AC5_14_1_reporting_assembles_framework_policy_results_only
@$be/infra/test_transaction_boundaries.py|P1
transaction-boundary.1|Service modules only call commit in documented background-task or streaming-response transaction-boundary exceptions.|test_service_commit_calls_are_documented_boundary_exceptions
transaction-boundary.2|Market-data persistence helpers use flush.|test_market_data_fx_persistence_is_rollbackable_until_boundary_commit
transaction-boundary.3|Market-data HTTP sync endpoints finalize service writes at the router boundary.|test_market_data_sync_endpoint_commits_service_writes_at_router_boundary
@$fe/__tests__/date.test.ts|P1
fe-utils.1|`formatDateInput` formats `Date` as `YYYY-MM-DD` with zero-padded month and day.|AC16.6.1 formats a date as YYYY-MM-DD string|P2
fe-utils.2|Formats a Date object to en-US short date.|AC16.6.2 formats a Date object to en-US short date
fe-utils.3|Formats a Date object with date and time.|AC16.6.3 formats a Date object with date and time
fe-utils.4|Returns short month name from date string.|AC16.6.4 returns short month name from date string
@$fe/__tests__/apiFunctions.test.ts|P2
fe-http-client.1|`apiFetch` returns JSON on `200` response.|AC16.10.1 returns JSON on 200 response
fe-http-client.2|`apiFetch` returns `undefined` on `204 No Content`.|AC16.10.2 returns undefined on 204 No Content
fe-http-client.3|`apiFetch` throws error with `detail` message on non-ok response.|AC16.10.3 throws with detail message on JSON error response
fe-http-client.4|`apiFetch` throws on non-JSON error text.|AC16.10.4 throws with raw text on non-JSON error response
fe-http-client.5|`apiFetch` calls `handle401Redirect` on `401` response.|AC16.10.5 redirects to /login on 401 unauthorized response
fe-http-client.6|`resetRedirectGuard` resets the redirect guard state.|AC16.10.6 resetRedirectGuard is exported and callable
fe-http-client.7|`apiDelete` succeeds on `200` response.|AC16.10.7 succeeds on 200 response
fe-http-client.8|`apiDelete` throws on non-ok response.|AC16.10.8 throws on non-ok response
fe-http-client.9|`apiStream` returns response and `sessionId` on success.|AC16.10.9 returns response and sessionId on success
fe-http-client.10|`apiStream` throws on non-ok response.|AC16.10.10 throws on non-ok response
fe-http-client.11|`apiUpload` returns JSON on `200` response.|AC16.10.11 returns JSON on 200 response
fe-http-client.12|`apiUpload` returns `undefined` on `204 No Content`.|AC16.10.12 returns undefined on 204 No Content
fe-http-client.13|`apiFetch` normalizes path without leading slash.|AC16.10.13 normalizes path without leading slash
fe-http-client.15|Handles 401 redirect in apiDelete.|AC16.10.15 handles 401 redirect in apiDelete|P1
fe-http-client.17|Handles 401 redirect in apiUpload.|AC16.10.17 handles 401 redirect in apiUpload|P1
fe-http-client.18|Throws with detail message on JSON error response.|AC16.10.18 throws with detail message on JSON error response|P1
fe-http-client.19|Throws with raw text on non-JSON error response.|AC16.10.19 throws with raw text on non-JSON error response|P1
fe-ia-nav.19|A typed user settings client.|AC22.15.1 get_current_user_settings_users_me_settings_get GETs /api/users/me/settings|P1
fe-http-client.21|Balance sheet, income statement.|AC5.17.1 downloads authenticated CSV blobs and preserves the server filename|P0
@$fe/__tests__/theme.test.ts|P2
fe-utils.5|`getTheme` returns stored value or system preference.|AC16.7.1 returns stored dark theme from localStorage
fe-utils.6|`setTheme` adds/removes `dark` CSS class and saves to `localStorage`.|AC16.7.2 adds dark class when setting dark theme
fe-utils.7|`toggleTheme` switches between dark and light.|AC16.7.3 toggles from light to dark
fe-utils.8|`initTheme` applies stored or system theme on load.|AC16.7.4 initializes theme from stored value
@$fe/__tests__/rootLayout.test.tsx|P2
fe-app-shell.6|Root layout composes `Providers` and `AuthGuard` around children.|AC16.17.5 composes Providers and AuthGuard around children
fe-app-shell.21|Root layout keeps theme color in the viewport export and avoids duplicate iOS web-app capability metadata.|AC16.25.4 root layout metadata keeps viewport-only theme color|P1
@$fe/__tests__/sidebarAndTabs.test.tsx|P1
fe-app-shell.8|Sidebar shows auth-aware actions and logout triggers `clearUser` plus login redirect.|AC16.19.3 AC22.21.2 shows auth-aware sidebar actions mirroring the bottom tabs|P2
fe-app-shell.9|Workspace tabs derive route labels and invoke add/set/remove tab handlers.|AC16.19.4 adds and manages workspace tabs from route changes|P2
fe-app-shell.13|Keeps the accounting machinery, sidebar badges and settings out of the sidebar.|AC15.7.7 AC16.19.12 AC19.6.3 AC19.6.4 AC19.6.5 AC22.21.1 keeps the accounting machinery, sidebar badges and settings out of the sidebar (supersedes the Advanced drawer)
fe-app-shell.14|WorkspaceTabs labels /portfolio tab as Portfolio from ROUTE_CONFIG.|AC16.19.13 WorkspaceTabs labels /portfolio tab as Portfolio from ROUTE_CONFIG
fe-app-shell.15|WorkspaceTabs section header is Open Tabs in both empty and active states.|AC16.19.14 WorkspaceTabs section header is Open Tabs in both empty and active states
fe-app-shell.16|Navigates workspace pages with ArrowRight keyboard.|AC16.19.15 AC16.30.3 AC16.30.4 navigates workspace pages with ArrowRight keyboard
fe-app-shell.32|`WorkspaceTabs` uses one coherent navigation/list semantic model with `aria-current` for the active route.|AC16.19.15 AC16.30.3 AC16.30.4 navigates workspace pages with ArrowRight keyboard|P2
fe-ia-nav.2|The sidebar brand links to `/` and the login flow redirects to `/`.|AC22.1.3 links the sidebar brand to Home
fe-ia-nav.26|The shell renders the bottom tab bar on mobile and mirrors the same five targets in the desktop sidebar.|AC16.19.3 AC22.21.2 shows auth-aware sidebar actions mirroring the bottom tabs
@$fe/__tests__/confirmDialogComponent.test.tsx|P2
fe-app-shell.10|Confirm dialog handles required input, cancel.|AC16.19.7 handles required input and confirm/cancel
fe-app-shell.11|Confirm dialog responds to escape key and backdrop click.|AC16.19.8 AC16.30.4 handles escape and backdrop cancellation
fe-app-shell.17|Renders dialog with ARIA attributes.|AC16.19.16 AC16.30.4 renders dialog with ARIA attributes|P1
fe-app-shell.18|Traps focus with Tab and Shift+Tab.|AC16.19.17 AC16.30.4 traps focus with Tab and Shift+Tab|P1
fe-app-shell.33|Component tests cover keyboard and ARIA behavior for dialog, sheet, toast, workspace navigation.|AC16.19.8 AC16.30.4 handles escape and backdrop cancellation
@$fe/__tests__/toastProviderComponent.test.tsx|P2
fe-app-shell.12|Toast provider shows, dismisses, and auto-expires notifications.|AC16.19.9 shows and dismisses notifications
fe-ia-nav.16|Shared toast and flow-step status affordances use Lucide icons or text.|AC22.12.5 uses semantic icon components instead of unicode glyph icons|P1
@$fe/__tests__/useWorkspaceHook.test.tsx|P2
fe-app-shell.19|Workspace provider restores tabs from storage and persists active workspace updates.|AC16.21.9 hydrates tabs from localStorage and keeps active tab
fe-app-shell.20|Workspace provider handles tab deduplication, removal.|AC16.21.10 deduplicates tabs by href and keeps existing active id
@$fe/__tests__/uiPrimitives.test.tsx|P2
fe-app-shell.22|Shared React UI primitives live under `apps/frontend/src/components/ui/` and cover button, icon button, badge, alert, empty state, loading state.|AC16.28.1 AC16.28.4 renders button and badge variants through shared primitives
fe-app-shell.23|Icon-only actions require an accessible label.|AC16.28.2 AC16.28.4 requires icon-only actions to expose an accessible label
fe-app-shell.25|Primitive component tests cover variants, accessibility-facing props.|AC16.28.1 AC16.28.4 renders button and badge variants through shared primitives
fe-app-shell.30|`IconButton` keeps its required `label` as the authoritative accessible name.|AC16.30.1 AC16.30.4 keeps IconButton label authoritative over passthrough props
fe-ia-nav.17|Data-dense report and asset-table loading states reserve layout with token-backed skeleton placeholders.|AC22.12.6 renders token-backed skeleton primitives without spinner affordances|P1
@$fe/__tests__/designTokens.test.tsx|P2
fe-app-shell.26|Tailwind theme extension maps frontend CSS-variable tokens for semantic color, radius, shadow/elevation, z-index, motion, typography.|AC16.29.1 AC16.29.4 maps Tailwind theme values to CSS-variable design tokens
fe-app-shell.27|Frontend CSS and SSOT document the design-token model.|AC16.29.2 AC16.29.4 documents token usage and page-local visual decisions in SSOT
fe-app-shell.28|Confidence and status UI components use semantic token-backed primitives.|AC16.29.3 AC16.29.4 renders ConfidenceBadge variants through semantic token classes
fe-app-shell.29|Frontend tests cover the token configuration contract and at least one tokenized semantic component.|AC16.29.1 AC16.29.4 maps Tailwind theme values to CSS-variable design tokens
fe-app-shell.31|The design-token follow-ups from issues #612 and #613 are resolved.|AC16.30.2 AC16.30.6 keeps SSOT and CSS recipes on semantic border and status tokens
fe-app-shell.35|Frontend SSOT documents the accessibility and visual-verification workflow required for future UI-system changes.|AC16.30.2 AC16.30.6 keeps SSOT and CSS recipes on semantic border and status tokens
fe-ia-nav.13|Global styles honor `prefers-reduced-motion: reduce` by disabling non-essential animation/transition timing and smooth scrolling.|AC22.12.1 AC22.12.3 AC22.13.3 defines the global accessibility baseline in SSOT and CSS|P1
fe-ia-nav.15|Global focus-visible styles cover links, form controls.|AC22.12.1 AC22.12.3 AC22.13.3 defines the global accessibility baseline in SSOT and CSS|P1
fe-ia-nav.18|Carryover accessibility review fixes keep the skip-link target covered by global focus-visible styling and keep report package table-of-contents section status in the accessible link name.|AC22.12.1 AC22.12.3 AC22.13.3 defines the global accessibility baseline in SSOT and CSS|P1
@$fe/__tests__/navigation.test.ts|P1
fe-ia-nav.1|Primary navigation renders a bottom tab bar of exactly five hit targets.|AC19.6.2 AC19.8.5 AC22.1.1 AC22.1.7 AC22.2.4 AC22.21.1 exposes a five-target bottom tab bar with distinct icons (Home, Chat, Add, Audit, More)
fe-ia-nav.5|`/assets` redirects to `/portfolio` and exactly one navigation entry is labeled "Portfolio".|AC22.1.6 lists Portfolio exactly once across the navigation model
fe-ia-nav.6|Chat and AI Settings navigation entries use distinct icons.|AC19.6.2 AC19.8.5 AC22.1.1 AC22.1.7 AC22.2.4 AC22.21.1 exposes a five-target bottom tab bar with distinct icons (Home, Chat, Add, Audit, More)
fe-ia-nav.9|The standalone Review Queue page is removed, `/review` redirects to `/upload`.|AC19.6.2 AC19.8.5 AC22.1.1 AC22.1.7 AC22.2.4 AC22.21.1 exposes a five-target bottom tab bar with distinct icons (Home, Chat, Add, Audit, More)
fe-ia-nav.20|No redirect path of the route map has a `ROUTE_CONFIG` entry.|AC22.18.1 keeps every redirect route of the route map out of ROUTE_CONFIG so no stale label leaks
fe-ia-nav.25|The navigation model exposes a bottom tab bar of Home, Chat, Audit.|AC19.6.2 AC19.8.5 AC22.1.1 AC22.1.7 AC22.2.4 AC22.21.1 exposes a five-target bottom tab bar with distinct icons (Home, Chat, Add, Audit, More)
fe-ia-nav.27|`/audit` renders a verify-on-demand hub aggregating Reconciliation, Journal, Statements.|AC22.21.3 folds the accounting machinery into the /audit hub, out of navigation
fe-ia-nav.29|`/more` lists low-frequency destinations.|AC22.21.5 routes low-frequency destinations through the /more overflow
fe-ia-nav.36|A workspace tab of a dynamic target page of the route map is labelled by the `ROUTE_CONFIG` entry of that page, never by its id.|AC-meta.fe-ia-nav.36 labels every dynamic target page of the route map by pattern, not by its parameter
@$fe/__tests__/nextConfigRedirects.test.ts|P1
fe-ia-nav.3|`/dashboard` redirects to `/` and the label "Upload Pipeline" no longer appears in the navigation model.|AC22.1.4 redirects the legacy dashboard route to Home
fe-ia-nav.4|`/events` redirects to `/upload` and the upload page renders the workflow event notices.|AC22.1.5 redirects /events to /upload
fe-ia-nav.7|`/upload` renders both the statement uploader and upload history.|AC22.1.8 redirects legacy statement routes to /upload
fe-ia-nav.28|`/settings` renders one page with General, AI.|AC22.21.4 redirects the legacy settings pages to the merged tabbed /settings
@$fe/__tests__/infoHint.test.tsx|P1
fe-ia-nav.11|Core jargon terms expose a plain-language explanation.|AC22.5.5 exposes the plain-language glossary text to assistive tech
fe-ia-nav.12|The reconciliation match-rate is shown under a single term on both Home and Reports, backed by one shared `InfoHint` glossary entry.|AC22.9.2 exposes a single reconciliation-coverage term for the unified label
@$fe/__tests__/pwaInstall.test.tsx|P1
fe-ia-nav.21|The install manifest uses the canonical `/` app launch route, stable app identity, standalone display.|AC22.20.1 keeps install manifest on the canonical home-screen launch contract
fe-ia-nav.22|The shared install hook captures Android/Chromium `beforeinstallprompt`, suppresses the browser's automatic prompt until the app-level action, invokes `prompt`.|AC22.20.2 captures Android beforeinstallprompt and invokes the deferred native prompt
fe-ia-nav.23|The global app-shell install prompt renders an Android install action.|AC22.20.3 renders the Android install action from the global app-shell prompt
fe-ia-nav.24|Installed or standalone sessions hide the install prompt.|AC22.20.4 detects iOS and standalone launch states without page code
@$fe/__tests__/routeMap.test.ts|P1
fe-ia-nav.31|The route map `apps/frontend/src/lib/route-map.json` lists every app page exactly once.|AC-meta.fe-ia-nav.31 lists each app page exactly once and gives redirect entries no page
fe-ia-nav.32|The route map keeps exactly 10 target pages, uses only the states target, shell and redirect with only the keys path, state and into.|AC-meta.fe-ia-nav.32 keeps exactly the target page count, only known states and keys, and sends every redirect to a live page
fe-ia-nav.33|The `next.config.mjs` redirects equal the redirect entries of the route map.|AC-meta.fe-ia-nav.33 makes next.config redirects equal the redirect entries
fe-ia-nav.34|Navigation links and the 30 flow UI surfaces point only at route map paths that are not redirects.|AC-meta.fe-ia-nav.34 points navigation links and the 30 flow UI surfaces only at paths that are not redirects
fe-audit-queue.1|The old routes `/attention`, `/confidence`, `/review/ai-suggestions` and `/review/run/[runId]` have no page.|AC-meta.fe-audit-queue.1 redirects each old audit-queue route to the Needs you tab of /audit and keeps the run id
fe-ia-nav.35|The route map redirects `/notifications`, `/processing` and `/accounts/processing` to `/upload`, `/statements/[id]/review` to `/statements/[id]`.|AC-meta.fe-ia-nav.35 redirects the upload-chain routes and keeps the legacy aliases off the retired notifications path
fe-reports-tabs.1|The old routes `/reports/balance-sheet`, `/reports/income-statement`, `/reports/cash-flow` and `/reports/package` have no page and redirect to `/reports?tab=<name>`.|AC-meta.fe-reports-tabs.1 redirects each old report route to its /reports tab and keeps the query
fe-tab-routes.1|The old routes `/reconciliation/unmatched`, `/reconciliation/review-queue`, `/portfolio/prices`, `/portfolio/evidence`, `/portfolio/[ticker]` and `/accounts` have no page.|AC-meta.fe-tab-routes.1 redirects each old reconciliation, portfolio and accounts route to a tab or a panel and keeps its query
@$fe/__tests__/auditHub.test.tsx|P1
fe-audit-queue.2|The `/audit` page shows one Needs Confirmation queue.|shows the confirmation rows and the AI suggestions of the three old queues on this one page
fe-audit-queue.3|The `/audit` page has the tabs Needs you, Health and Books, selected by `?tab=`.|AC-meta.fe-audit-queue.3 opens on Needs you while an item needs the user and on Health when none does
fe-audit-queue.4|The Health tab of `/audit` shows no audit-ready grade or text.|AC-meta.fe-audit-queue.4 shows no audit-ready grade while an unmatched row or a blocker exists
@$fe/__tests__/contractTypes.test.ts|P1
fe-contract-types.1|The list-response envelope has a single `ListResponse<T>` definition and the per-entity list responses derive from it.|AC25.3.1: every list response derives from the single ListResponse<T> envelope
fe-contract-types.2|`lib/api.ts` is the single raw-`fetch` boundary.|AC25.3.2: lib/api.ts is the single raw-fetch boundary in the frontend
@$t/test_governance_control_plane.py|P0
governance-control.1|Package contracts own governance initiatives and guarantees.|test_AC_meta_governance_control_1_contract_and_roadmap_projection_are_lossless
governance-control.2|One pure joined projection connects package initiative, guarantee, affected ACs, detector result, exact proof outcome.|test_AC_meta_governance_control_2_completion_is_derived_from_joined_facts
governance-control.3|The governance report lists package initiatives with current and target progress plus open or blocked guarantee counts.|test_AC_meta_governance_control_3_report_exposes_summary_and_exact_detail
governance-control.4|Proof policy distinguishes reference-only, report-only, stale, non-required.|test_AC_meta_governance_control_4_weak_stale_and_non_required_proof_stays_red
governance-control.5|Declared blocking gates, workflow aggregation.|test_AC_meta_governance_control_5_enforcement_reconciliation_fails_closed
governance-control.6|Package governance fails closed unless every required guarantee is backed by a complete current-SHA observation bundle whose detector, independent serialized executed proof, issue state, workflow aggregation.|test_AC_meta_governance_control_6_cli_fails_closed_on_unproven_guarantees|:exact
@$t/test_governance_ratchet.py|P0|done|exact
governance-ratchet.1|Every flat router in apps/backend/src/routers/ and schema module in apps/backend/src/schemas/ is classified in the package governance census with an explicit shrink-only ratchet.|test_AC_meta_governance_ratchet_1_app_ownership
governance-ratchet.2|Backend root module boundaries are tracked in the package governance census and enforced shrink-only.|test_AC_meta_governance_ratchet_2_domain_locality
governance-ratchet.3|Public Python signatures and app-root composition boundaries are counted and governed.|test_AC_meta_governance_ratchet_3_python_boundary_denominator
governance-ratchet.4|Frontend production discovery covers all active modules and exports.|test_AC_meta_governance_ratchet_4_frontend_export_denominator
governance-ratchet.5|Frontend operation consumer discovery confirms retired api.ts wrappers converge to direct callers, classifying OpenAPI operations as consumed.|test_AC_meta_governance_ratchet_5_operation_consumer_truth
governance-ratchet.6|Unused OpenAPI operations are partitioned honestly between intentional API-only operations and consumer gaps.|test_AC_meta_governance_ratchet_6_unused_operation_honesty
governance-ratchet.7|The delivery surface migration debt remains visible with semantic owner and shrink-only status.|test_AC_meta_governance_ratchet_7_delivery_surface_truth
governance-ratchet.8|DDD unit accountability enforces that all declared bounded context units are accounted for, unbound units are tracked with shrink-only limits.|test_AC_meta_governance_ratchet_8_unit_accountability
governance-ratchet.9|Empty app discovery, skipped frontend roots, excluded wrapper files.|test_AC_meta_governance_ratchet_9_non_vacuity
governance-ratchet.10|Package governance integration runs exhaustive denominator census and ratchet verification.|test_AC_meta_governance_ratchet_10_governance_integration
@-|P1
dependency-governance.1|The computed dependency index projects package contracts into typed edges plus deterministic direct and transitive consumers.|$t/test_dependency_graph.py::test_AC_meta_dependency_governance_1_projection_has_typed_edges_and_transitive_consumers|P0
dependency-governance.3|L4 delivery code may reach another package only.|$t/test_app_boundary.py::test_AC_meta_dependency_governance_3_l4_deep_imports_are_exact|P0
dependency-governance.4|Production package base layers have no new ORM, configuration, observability, network, or session dependency.|$t/test_base_purity.py::test_AC_meta_dependency_governance_4_base_impurity_is_exact|P0
dependency-governance.5|ORM-defined types are not silently added to package-root public language.|$t/test_public_orm_exports.py::test_AC_meta_dependency_governance_5_public_orm_exports_are_exact|P0
dependency-governance.6|Every declared package unit is implementation-bound or remains in an exact shrink-only accountability baseline.|$t/test_unit_accountability.py::test_AC_meta_dependency_governance_6_unit_accountability_is_exact|P0
public-boundary.3|Production frontend requests bind path, method, parameters, body, success response.|$fe/__tests__/untypedTransportLint.test.ts::AC-meta.public-boundary.3 rejects every import and call of an untyped transport|P0
context-governance.1|A package can publish its bounded-context purpose, explicit responsibility boundary.|$t/test_context_contract.py::test_AC_meta_context_governance_1_context_scope_rejects_empty_purpose|P0
context-governance.2|Aggregate roots, entities, value objects.|$t/test_semantic_ownership.py::test_AC_meta_context_governance_2_duplicate_semantic_owner_fails|P0
vocab.1|Retired taxonomy vocabulary presented as current truth in docs/SSOT/EPIC/test prose fails the taxonomy-drift gate.|$t/test_taxonomy_drift.py::test_AC_meta_vocab_1_repo_is_clean
AC-authority.7.1|CODE-ONLY / financial-truth modules are statically proven free of LLM-layer imports.|$t/test_tier_imports.py::test_AC26_7_1_real_tree_has_no_llm_imports_in_protected_modules|P0:property
router.1|No backend router module imports a symbol from another router.|$be/api/test_router_boundary.py::test_AC25_5_1_no_router_imports_another_router
ssot-governance.7|FR and infra2 each document a 6-8 family SSOT HLS model with explicit concept/clause boundaries covering every MANIFEST.yaml-inferred family, linking #821/#822/#823/#824.|$t/test_ssot_hls_family_model.py::test_AC14_1_18_fr_hls_family_model_is_documented_and_consistent
governance-baseline.2|Every temporary SSOT governance exception has one unique target, an issue URL, a reason.|$t/test_governance_exceptions_registry.py::test_AC_meta_governance_baseline_2_gate_rejects_stale_or_ambiguous_ssot_exceptions|P0
issue-templates.1|GitHub issue templates require phenomenon, reproduction, minimal-fix.|$t/test_issue_template_contract.py::test_AC14_1_11_issue_templates_carry_their_type_required_fields
generated-refs.1|The DB schema inventory is generated from SQLAlchemy metadata by tools/generate_db_schema_reference.py at MkDocs build time.|$t/test_generate_db_schema_reference.py::test_AC14_1_17_render_db_schema_reference_uses_sqlalchemy_metadata
generated-refs.3|README EPIC status is a generated pointer block to the on-demand per-EPIC traceability table and is guarded by a generate-with--check drift gate.|$t/test_generate_epic_status.py::test_AC14_1_22_check_fails_on_drift
infra-boundary.8|The published :<sha> frontend image is environment-independent.|$t/test_frontend_same_origin_contract.py::test_AC7_12_8_published_frontend_image_has_no_baked_env_domain|P0
delivery.1|Routers/ and schemas/ are the sanctioned app delivery layer.|$t/test_delivery_layer_ratchet.py::test_AC_meta_delivery_1_delivery_layer_only_thins
residue.1|Every AC definition line that stays in a docs/project/EPIC-*.md doc carries an explicit residue marker declaring why it is not in a package roadmap.|$t/test_epic_residue_ratchet.py::test_AC_meta_residue_1_census_equals_baseline_and_files_only_shrink|P0
residue.2|Docs/ssot/ does not exist.|$t/test_terminal_centers_allowlist.py::test_docs_project_directory_listing_is_frozen
phase0.6|SQLAlchemy + Alembic config is valid.|$be/infra/test_schema_drift.py::test_missing_migrations_check
workflow-events.1|The workflow notification UI contract is documented in the workflow-events SSOT and EPIC-019.|$be/workflow/test_workflow_events.py::test_AC19_3_8_workflow_notification_ssot_documents_frontend_surfaces
fe-app-shell.1|FirstRunModal dismissal persists in localStorage.|$fe/__tests__/uxDefaultPeriodAndFirstRun2763.test.tsx::AC-meta.fe-app-shell.1 persists FirstRunModal dismissal in localStorage across remounts and tucks protocol/base URL under Advanced settings|P2
fe-app-shell.4|Root resolves to the authenticated Home entry.|$fe/__tests__/dashboardPage.test.tsx::AC16.12.3 AC22.1.2 renders the dimension bar and the three statement cards of the period|P2
fe-app-shell.5|Main layout renders children through `AppShell` wrapper.|$fe/__tests__/mainLayout.test.tsx::AC16.16.2 renders children through AppShell|P2
fe-app-shell.7|`Providers` wraps children with `QueryClientProvider`.|$fe/__tests__/providers.test.tsx::AC16.17.6 wraps children with QueryClientProvider|P2
fe-http-client.20|API catch-all handlers return JSON `503` for all HTTP methods.|$fe/__tests__/apiCatchAllRoute.test.ts::AC16.17.7 returns 503 JSON for all supported methods|P2
fe-app-shell.24|At least two representative frontend pages are migrated to the primitive layer.|$fe/__tests__/accountsPage.test.tsx::AC16.28.2 AC16.28.3 exposes account row icon actions with accessible labels|P2
fe-app-shell.34|Playwright visual smoke covers desktop and mobile representative app-shell, accounts, statements.|apps/frontend/playwright/ui-visual-smoke.spec.ts::captures representative app-shell, accounts, statements, and review pages|P2
fe-ia-nav.8|Desktop and mobile smoke covers the five-target bottom-tab navigation and the notification bell.|apps/frontend/playwright/epic022-ia-shell.spec.ts::desktop sidebar mirrors the five bottom-tab targets and the notification bell
fe-ia-nav.10|The upload, statement-detail.|$fe/__tests__/flowStepBanner.test.tsx::AC22.5.1 renders the Upload -> Review & approve -> Reports path
fe-ia-nav.14|The authenticated shell exposes a skip-to-content link that targets the main landmark.|$fe/__tests__/shellAndAuth.test.tsx::AC22.12.2 exposes a skip-to-content link targeting the main landmark
fe-ia-nav.30|Desktop and mobile smoke covers the bottom tab bar, the Add sheet, the Audit hub.|apps/frontend/playwright/epic022-bottom-tab-ia.spec.ts::the bottom bar opens the Add sheet with both ways to add
fe-audit-queue.5|`/audit` shows the Needs Confirmation heading and its first row in the first viewport at 375x812 and at 1280x800.|apps/frontend/playwright/needs-you-front-door.spec.ts::AC-meta.fe-audit-queue.5 /audit shows the Needs Confirmation list in the first viewport (${label})
fe-http-client.22|Frontend `apiFetch` throws `ApiError` carrying the parsed `errorId`.|$fe/__tests__/apiErrorStructured.test.ts::test_AC12_27_3_api_error_carries_error_id parses error_id from the body
fe-app-shell2.1|`<ConfidenceBadge />` component renders `TRUSTED` / `HIGH` / `MEDIUM` / `LOW` pill with consistent color tokens and tooltip explaining source-type priority.|$fe/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx::AC18.5.1 — ConfidenceBadge renders confidence tier labels|P2
fe-http-client.23|High-traffic call sites type responses against the generated schema.|$fe/__tests__/apiTypedClient.test.ts::test_AC12_28_3_types_stage2_batch_responses_against_generated_schema|P2
fe-contract-types.3|No component-local `interface FooResponse`/`interface FooRequest` wire-shape declarations exist outside `lib/`.|$t/test_fe_wire_type_ssot.py::test_AC_fe_wire_ssot_1_no_hand_declared_response_request_outside_lib
fe-contract-types.4|`countLabel`/`pnlColorClass`/`formatPeriod`/`isActive`/`readinessVariant` each have at most one definition, at one canonical home.|$t/test_fe_helper_ssot.py::test_AC_fe_helper_ssot_1_each_helper_defined_at_most_once|P2
fe-contract-types.5|No file under `apps/frontend/src/components/workflow/` exceeds 300 lines.|$t/test_fe_no_godfile.py::test_AC_fe_no_godfile_1_workflow_files_stay_under_300_lines|P2
fe-contract-types.6|Down-only frontend layer boundaries are enforced.|$t/test_fe_layer_boundaries.py::test_AC_fe_layer_boundaries_1_lib_never_imports_components_or_app
""",
    ),
    concepts=concepts(
        """
governance_ratchet_baseline|common/meta/data/governance-ratchet-baseline.json|Exhaustive shrink-only baseline locking 21 flat routers, 23 schemas, 9 backend root composition modules, and 104 unbound DDD units in the package governance census.|common/meta/data/governance-ratchet-baseline.json,common/meta/extension/governance_census.py,common/meta/extension/governance_detector.py,tools/report_package_governance.py,tests/tooling/test_governance_ratchet.py|tests/tooling/test_governance_ratchet.py|platform|baseline|machine_generated|package_model
ac_tier_baseline|common/meta/data/ac-tier-baseline.json|Shrink-only untagged-AC debt baseline for the authority-tier ratchet (tools/check_ac_tier_baseline.py); lists ACs that predate the tier attribute and may stay untagged, so new/changed ACs must declare a tier while legacy debt ratchets down.|common/meta/readme.md,common/meta/extension/check_ac_tier_baseline.py,tools/check_ac_tier_baseline.py,tests/tooling/test_ac_authority_tiers.py|-|tdd|baseline|machine_generated|authority_tiers
app_boundary_baseline|common/meta/extension/check_app_boundary.py|In-code absolute zero-debt assertion of cross-boundary edges between the apps/backend/src remainder and carved packages; check_app_boundary rejects any newly introduced leak or upward edge.|common/meta/migration-standard.md,common/meta/extension/app_boundary.py,tools/check_app_boundary.py,tests/tooling/test_app_boundary.py|-|platform|concept|-|package_model
l4_root_import_baseline|common/meta/extension/app_boundary.py|In-code absolute zero-debt assertion of statement-level deep imports from the L4 delivery/composition shell into package internals.|common/meta/extension/check_app_boundary.py,tools/check_app_boundary.py,tests/tooling/test_app_boundary.py|-|platform|concept|-|package_model
unit_accountability_baseline|common/meta/data/unit-accountability-baseline.json|Exact shrink-only inventory of declared units without an implementation path and repositories without a complete base-port/extension-adapter pair.|common/meta/extension/check_unit_accountability.py,tools/check_unit_accountability.py,tests/tooling/test_unit_accountability.py|-|platform|baseline|machine_generated|package_model
authority_tiers|common/meta/readme.md|The five AC authority tiers (CODE-ONLY/CODE-LED/HU/LLM-LED/LLM-ONLY), the cross-tier MUST rules, and the tier->valid-proof matrix; one AC = one tier, declared via a {tier:XX} marker at the AC definition site and ratcheted by a shrink-only untagged-debt baseline. Internalized into the authority package (migration-standard step 3); the central docs/ssot/authority-tiers.md is retired.|common/testing/tdd.md,common/llm/ai.md,common/extraction/readme.md,docs/project/EPIC-026.ac-authority-tiers.md,common/meta/data/ac-tier-baseline.json,common/meta/extension/generate_ac_registry.py,common/meta/base/authority_matrix.py,common/meta/extension/check_ac_tier_baseline.py,tools/check_ac_tier_baseline.py,common/meta/extension/check_tier_ast_literal.py,common/meta/extension/check_draft_packages.py,common/meta/extension/authority_classifier.py,common/meta/extension/check_authority_reconcile.py|tests/tooling/test_ac_authority_tiers.py|tdd|concept|documented_contract|tdd_workflow
data_layering|common/meta/schema.md#data-layering|ODS/DWD/DWM/DWS/ADS/DIM classification of every data table and cross-layer rules.|common/extraction/readme.md,common/reconciliation/reconciliation.md,docs/project/EPIC-011.asset-lifecycle.md|-|schema|concept
database_schema|common/meta/schema.md#er-model|PostgreSQL schema rationale, generated inventory reference, and migration rules.|docs/reference/api-overview.md,docs/hooks.py,tools/generate_db_schema_reference.py,common/meta/extension/generate_db_schema_reference.py,common/ledger/readme.md,common/reconciliation/reconciliation.md|tests/tooling/test_generate_db_schema_reference.py,apps/backend/tests/infra/test_schema_guardrails.py|schema|concept|documented_contract
delivery_gate_triggers|common/meta/data/delivery-gates.yaml|How each delivery CI gate triggers and whether it blocks merge — the single source for trigger/blocking contracts (so a trigger change is one edit, not a fact restated across docs/tests).|common/testing/ci-cd.md,common/runtime/environments.md,docs/project/EPIC-008.testing-strategy.md,runtime-hooks.manifest.json|tests/tooling/test_delivery_gates_contract.py|delivery|matrix
delivery_layer_baseline|common/meta/data/delivery-layer-baseline.json|Thin-ness ratchet census of the sanctioned app delivery layer — per-directory *.py line totals of apps/backend/src/routers (HTTP delivery adapters) and apps/backend/src/schemas (API DTOs), which are hexagonal primary adapters, not domain behavior (#1763 ruling); CI enforces the census stays within a 50-line band of the baseline, so silent growth fails and growing the delivery layer requires a same-PR baseline edit (reviewable consent), while meaningful shrink lowers the baseline in the same PR to keep the ratchet tight; the delivery layer's bulk may only shrink as packages absorb logic (AC-meta.delivery.1).|tests/tooling/test_delivery_layer_ratchet.py,common/meta/migration-standard.md|-|platform|baseline|machine_generated|package_model
draft_package_baseline|common/meta/extension/check_draft_packages.py|In-code absolute zero-debt assertion for draft-package hygiene; un-baselined draft packages and finished work in draft are strictly prohibited.|common/meta/readme.md,tests/tooling/test_migration_safety_gates.py|-|tdd|concept|-|authority_tiers
enum_naming|common/meta/schema.md#enum-naming|All sa.Enum instances MUST have an explicit name parameter.|AGENTS.md,docs/agents/red-lines.md,apps/backend/tests/infra/test_schema_guardrails.py|-|schema|concept
context_contract_debt_baseline|common/meta/extension/check_context_contract.py|In-code absolute zero-debt assertion for package-owned bounded-context declarations; unclassified dependencies or missing contexts are strictly prohibited.|common/meta/base/package_contract.py,tests/tooling/test_context_contract.py|-|platform|concept|-|package_model
environment_variables|common/meta/development.md#environment-variables|App env SSOT generated from config.py into .env.example and required-env manifest.|docs/agents/red-lines.md,common/runtime/deployment.md,.env.example,apps/backend/src/config.py,common/runtime/required-env.generated.json,apps/backend/src/runtime/extension/env_keys.py,apps/backend/src/runtime/extension/schema_validation.py,tools/check_env_keys.py,tools/validate_schemas.py,tools/generate_env_reference.py,.pre-commit-config.yaml|-|development|concept
local_host_shells|common/meta/development.md#local-host-shell-matrix|Supported local command shells and PATH/tool-install boundaries across WSL Ubuntu, macOS/Linux, Windows PowerShell, and Codex runner contexts.|README.md,common/runtime/environments.md#host-shell-boundaries,tools/bootstrap.sh,common/runtime/shell/,common/runtime/shell/common.sh|-|development|matrix
migration_risk_classification|common/meta/data/migration-risk.yaml|Machine-readable risk level and release proof contract for Alembic migrations.|common/meta/schema.md,common/testing/ci-cd.md,common/runtime/deployment.md,tools/check_migration_risk.py,common/meta/extension/migration_risk.py,tests/tooling/test_migration_risk_contract.py|-|delivery|concept
moon_commands|common/meta/development.md#moon-commands|Primary interface for dev, lint, test, and build tasks.|AGENTS.md,docs/contributing/branch-policy.md|-|development|playbook
namespace_isolation|common/meta/development.md#local-test-isolation|Namespace-based test DB and S3 bucket isolation for parallel runs.|common/runtime/environments.md|-|development|concept
package_model|common/meta/readme.md#package-model|A package = a DDD bounded context (readme.md + PackageContract + base/extension/data layers carrying DDD building-block units + __all__ published language); placement resolved from the central five-layer map `PACKAGE_LAYER` (`meta < infra < middleware < domain < app`; defined in `common/meta/base/layering.py`); governance is computed from contracts by check_package_contract. The model self-hosts in the common/meta package (base = model, extension = gate, data = projection).|common/meta/base/package_contract.py,common/meta/extension/check_package_contract.py,common/meta/data/projection.py,common/meta/contract.py,common/counter/readme.md,common/counter/contract.py,apps/backend/src/counter/__init__.py,common/identity/readme.md,common/identity/contract.py,apps/backend/src/identity/__init__.py,common/ledger/contract.py,docs/project/EPIC-025.dry-ssot-simplification.md|tests/tooling/test_counter_package.py|platform|concept|documented_contract
runtime_toolchain|common/meta/development.md#toolchain-contract|Python, Node.js, uv, and container image versions shared by local, CI, and Docker environments.|toolchain.toml,tools/bootstrap.sh,common/runtime/shell/bootstrap.sh,common/runtime/shell/common.sh,tools/check_toolchain_contract.py,common/runtime/check_toolchain_contract.py,.moon/toolchain.yml,.github/workflows/ci.yml,docker-compose.yml|-|development|concept
ssot_governance_exceptions|common/meta/data/governance-exceptions.yaml|Machine-readable temporary exception registry for incremental SSOT governance gate findings.|common/testing/tdd.md,common/meta/extension/governance_report/_gate.py,tests/tooling/test_ssot_governance_report.py|-|tdd|registry|-|ssot_governance_gates
error_taxonomy|common/meta/data/error-taxonomy.yaml|Authoritative SSOT taxonomy defining domain error codes, severity levels, remediation actions, and translations.|common/meta/data/error-taxonomy.yaml,apps/backend/src/schemas/errors.py|-|extraction|registry
thirty_wealth_flows|common/meta/flows/thirty_flows_ssot.json|Authoritative registry for the 30 core wealth and accounting flows.|docs/reference/thirty-wealth-flows.md,docs/reference/api-overview.md|apps/backend/tests/flows/test_thirty_flows_consistency.py,apps/frontend/src/__tests__/thirtyFlowsConsistency.test.tsx|accounting|registry|machine_generated
"""
    ),
    governance=[
        GovernanceInitiative(
            id="governance-control-plane",
            title="Package governance control plane",
            issue="https://github.com/wangzitian0/finance_report/issues/1983",
            guarantees=[
                GovernanceGuarantee(
                    id="lossless-roadmap-projection",
                    statement="Roadmap and governance declarations project without loss or overwrite.",
                    affected_acs=["AC-meta.governance-control.1"],
                    detector="package-governance-control-integrity",
                    target="source records equal unique projected records",
                    lock="ci.tooling_coverage",
                    proof="governance-control-lossless",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
                GovernanceGuarantee(
                    id="derived-joined-state",
                    statement="Completion is derived from joined target, proof, and enforcement facts.",
                    affected_acs=["AC-meta.governance-control.2"],
                    detector="package-governance-control-integrity",
                    target="zero missing joins",
                    lock="ci.tooling_coverage",
                    proof="governance-control-derived-state",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
                GovernanceGuarantee(
                    id="summary-and-detail",
                    statement="Stable package summaries drill into exact guarantee evidence.",
                    affected_acs=["AC-meta.governance-control.3"],
                    detector="package-governance-control-integrity",
                    target="zero missing detail coordinates",
                    lock="ci.tooling_coverage",
                    proof="governance-control-report",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
                GovernanceGuarantee(
                    id="proof-strength",
                    statement="Weak, stale, or non-required evidence cannot satisfy a guarantee.",
                    affected_acs=["AC-meta.governance-control.4"],
                    detector="package-governance-control-integrity",
                    target="zero invalid proof promotions",
                    lock="ci.tooling_coverage",
                    proof="governance-control-proof-strength",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
                GovernanceGuarantee(
                    id="enforcement-and-work-truth",
                    statement="Workflow, live ruleset, and issue observations reconcile fail closed.",
                    affected_acs=["AC-meta.governance-control.5"],
                    detector="package-governance-control-integrity",
                    target="zero missing or contradictory observations",
                    lock="ci.tooling_coverage",
                    proof="governance-control-enforcement",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
                GovernanceGuarantee(
                    id="live-observation-pipeline",
                    statement=(
                        "Only complete current-SHA independent observations can make "
                        "package governance green and merge-enforced."
                    ),
                    affected_acs=["AC-meta.governance-control.6"],
                    detector="package-governance-control-integrity",
                    target="zero missing, stale, self-certified, or unenforced observations",
                    lock="ci.tooling_coverage",
                    proof="package-governance-live-observation-policy",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
            ],
        ),
        GovernanceInitiative(
            id="app-and-frontend-governance",
            title="Make app and frontend governance discovery exhaustive",
            issue="https://github.com/wangzitian0/finance_report/issues/1984",
            depends_on=["meta/governance-control-plane"],
            guarantees=[
                GovernanceGuarantee(
                    id="app-ownership",
                    statement="Every backend router, schema, and root module is accounted for under package governance or an explicit shrink-only ratchet.",
                    affected_acs=["AC-meta.governance-ratchet.1"],
                    detector="governance-ratchet-status",
                    target="zero unratcheted delivery surfaces",
                    lock="ci.tooling_coverage",
                    proof="governance-ratchet-app-ownership",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
                GovernanceGuarantee(
                    id="domain-locality",
                    statement="Backend root modules remain bounded to authorized platform orchestration; unauthorized domain leakage fails closed.",
                    affected_acs=["AC-meta.governance-ratchet.2"],
                    detector="governance-ratchet-status",
                    target="zero unauthorized backend root modules",
                    lock="ci.tooling_coverage",
                    proof="governance-ratchet-domain-locality",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
                GovernanceGuarantee(
                    id="python-boundary-denominator",
                    statement="All backend public symbols and schemas are classified in the governance denominator.",
                    affected_acs=["AC-meta.governance-ratchet.3"],
                    detector="governance-ratchet-status",
                    target="zero unclassified python boundary schemas",
                    lock="ci.tooling_coverage",
                    proof="governance-ratchet-python-boundary-denominator",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
                GovernanceGuarantee(
                    id="frontend-export-denominator",
                    statement="Frontend production scan discovers all production modules without vacuous or silent exclusion.",
                    affected_acs=["AC-meta.governance-ratchet.4"],
                    detector="governance-ratchet-status",
                    target="zero vacuous or dropped frontend modules",
                    lock="ci.tooling_coverage",
                    proof="governance-ratchet-frontend-export-denominator",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
                GovernanceGuarantee(
                    id="operation-consumer-truth",
                    statement="Frontend API client wrapper calls are discovered as valid operation consumers.",
                    affected_acs=["AC-meta.governance-ratchet.5"],
                    detector="governance-ratchet-status",
                    target="zero falsely unconsumed wrapper operations",
                    lock="ci.tooling_coverage",
                    proof="governance-ratchet-operation-consumer-truth",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
                GovernanceGuarantee(
                    id="unused-operation-honesty",
                    statement="Unused OpenAPI operations are fully partitioned with zero unaccounted endpoints.",
                    affected_acs=["AC-meta.governance-ratchet.6"],
                    detector="governance-ratchet-status",
                    target="zero unaccounted OpenAPI operations",
                    lock="ci.tooling_coverage",
                    proof="governance-ratchet-unused-operation-honesty",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
                GovernanceGuarantee(
                    id="delivery-surface-truth",
                    statement="All flat routers and schema modules are subject to shrink-only baselines.",
                    affected_acs=["AC-meta.governance-ratchet.7"],
                    detector="governance-ratchet-status",
                    target="zero expanded flat routers or schemas",
                    lock="ci.tooling_coverage",
                    proof="governance-ratchet-delivery-surface-truth",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
                GovernanceGuarantee(
                    id="unit-accountability",
                    statement="DDD bounded context units are strictly accounted for and unbound units shrink only.",
                    affected_acs=["AC-meta.governance-ratchet.8"],
                    detector="governance-ratchet-status",
                    target="zero increased unbound units and zero incomplete splits",
                    lock="ci.tooling_coverage",
                    proof="governance-ratchet-unit-accountability",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
                GovernanceGuarantee(
                    id="non-vacuity",
                    statement="Governance census fails closed if discovered counts are zero or suspiciously drop below baseline.",
                    affected_acs=["AC-meta.governance-ratchet.9"],
                    detector="governance-ratchet-status",
                    target="zero vacuous census runs",
                    lock="ci.tooling_coverage",
                    proof="governance-ratchet-non-vacuity",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
                GovernanceGuarantee(
                    id="governance-integration",
                    statement="CLI reports and CI gates verify package governance ratchet and census integrity.",
                    affected_acs=["AC-meta.governance-ratchet.10"],
                    detector="governance-ratchet-status",
                    target="zero unverified package governance runs",
                    lock="ci.tooling_coverage",
                    proof="governance-ratchet-governance-integration",
                    required_proof_strength="exact",
                    enforcing_gate="ci.tooling_coverage",
                ),
            ],
        ),
    ],
)

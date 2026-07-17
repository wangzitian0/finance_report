# Traceability Exceptions

> Generated from the issue #475 audit on 2026-05-21.
> Updated for issue #511 on 2026-05-26.
> Updated for E2E AC ownership cleanup on 2026-05-28.
> Updated for storage sweep AC ownership on 2026-05-29.

The project proof chain is `README.md -> docs/project/EPIC-*.md ->
docs/*_registry.yaml -> tests`. Tests that assert product behavior should carry
an `ACx.y.z` reference. The files below are the current exception set: they are
not counted as AC proof and are classified so they do not become hidden drift.

## Test Files Without AC References

### Package Markers And Shared Test Harness

These files are test infrastructure, not behavior proof.

| Path | Classification |
|---|---|
| `apps/backend/tests/__init__.py` | Package marker |
| `apps/backend/tests/accounting/__init__.py` | Package marker |
| `apps/backend/tests/audit/money/__init__.py` | Package marker |
| `apps/backend/tests/audit/promotion/__init__.py` | Package marker |
| `apps/backend/tests/audit/quantity/__init__.py` | Package marker |
| `apps/backend/tests/audit/ratio/__init__.py` | Package marker |
| `apps/backend/tests/audit/trace/__init__.py` | Package marker |
| `apps/backend/tests/audit/trace/conftest.py` | Generated TraceRecord fixtures with no user financial data |
| `apps/backend/tests/audit/unit_price/__init__.py` | Package marker |
| `apps/backend/tests/ledger/__init__.py` | Package marker |
| `apps/backend/tests/ledger/_ledger_helpers.py` | Published ledger test factory (shared posted/void entry builders) |
| `tests/tooling/_infra2_source.py` | Shared helper (not a test): resilient resolver for infra2 deploy-primitive source; see #1519 |
| `apps/backend/tests/ai/__init__.py` | Package marker |
| `apps/backend/tests/ai/conftest.py` | Shared advisor fixtures: pins the env AI-key surface so tests are hermetic to ambient provider keys (#1804) |
| `apps/backend/tests/assets/__init__.py` | Package marker |
| `apps/backend/tests/identity/__init__.py` | Package marker |
| `apps/backend/tests/conftest.py` | Shared backend pytest fixtures |
| `apps/backend/tests/counter/__init__.py` | Package marker |
| `apps/backend/tests/counter/_fake.py` | In-memory counter store fake for ops unit tests |
| `apps/backend/tests/reconciliation/conftest.py` | EPIC-011 PR-B Layer-2 read bridge fixture |
| `apps/backend/tests/e2e/conftest.py` | Shared E2E fixtures |
| `apps/backend/tests/extraction/__init__.py` | Package marker |
| `apps/backend/tests/factories.py` | Shared backend test factories |
| `apps/backend/tests/infra/__init__.py` | Package marker |
| `apps/backend/tests/locustfile.py` | Load-test harness, not AC proof |
| `apps/backend/tests/market_data/__init__.py` | Package marker |
| `apps/backend/tests/metrics/__init__.py` | Package marker |
| `apps/backend/tests/platform/__init__.py` | Package marker |
| `apps/backend/tests/portfolio/__init__.py` | Package marker |
| `apps/backend/tests/reconciliation/__init__.py` | Package marker |
| `apps/backend/tests/reporting/__init__.py` | Package marker |
| `apps/backend/tests/reporting/_report_fixtures.py` | Shared reporting chart-of-accounts test builder |
| `apps/backend/tests/tooling/__init__.py` | Package marker |
| `apps/backend/tests/tooling/test_no_models_facade.py` | Code-contract lint: forbids reintroducing src.models, now fully dissolved (issue #1461, #1675 D6) |
| `tests/tooling/__init__.py` | Package marker |
| `tests/tooling/conftest.py` | Shared tooling-test fixtures |
| `tests/e2e/conftest.py` | Shared top-level E2E fixtures |
| `tests/e2e/pdf_fixture_paths.py` | Shared helper (not a test): PDF fixture path resolution for provider-backed journeys (#1613) |
| `apps/backend/tests/unit/conftest.py` | Shared unit fixtures |
| `apps/frontend/src/__tests__/helpers/renderReviewComponent.tsx` | Shared frontend render helper |

### SSOT Or Code-Contract Hardening Tests

These files are real tests, but they protect cross-cutting contracts rather
than owning EPIC acceptance criteria. They are not AC proof until an EPIC adds
explicit AC IDs for the behavior.

| Path | Owner |
|---|---|
| `tests/tooling/test_smoke_min_checks.py` | `common/runtime/readme.md` (env_smoke_test owned by the runtime package) |
| `tests/tooling/test_runtime_ssot_internalized.py` | `common/runtime/readme.md` (guards that the env-smoke-test SSOT stays internalized in the runtime package — the retired central doc is not resurrected) |
| `apps/backend/tests/audit/money/test_money.py` | `common/ledger/readme.md` |
| `apps/backend/tests/ledger/test_processing_account_endpoints.py` | `common/ledger/readme.md` |
| `apps/backend/tests/api/test_ai_feedback_router_extra.py` | `common/llm/ai.md` |
| `apps/backend/tests/assets/test_assets_positions_and_depreciation.py` | `common/portfolio/assets.md` |
| `apps/backend/tests/identity/test_auth_router_unit.py` | `common/identity/readme.md` |
| `apps/backend/tests/runtime/test_manifest.py` | `common/runtime/readme.md` |
| `apps/backend/tests/extraction/test_account_last4_defense.py` | `common/extraction/readme.md` |
| `apps/backend/tests/unit/test_1675_denavigation_seams.py` | `common/meta/migration-standard.md` (#1675 D4/D5c de-navigation seams: provider-port fail-fast + empty-input batch-fetch guards) |
| `apps/backend/tests/extraction/test_classification_service.py` | `common/extraction/readme.md` |
| `apps/backend/tests/extraction/test_extraction_cassette_replay.py` | `common/llm/readme.md` (EPIC-023 AC23.6 streaming-bridge scaffold; skipped via `needs_real_cassette` until real cassettes are recorded with `make llm-record`, then it becomes AC proof) |
| `apps/backend/tests/extraction/test_dual_write_layer2.py` | `common/extraction/readme.md` |
| `apps/backend/tests/extraction/test_extraction_logging.py` | `common/extraction/readme.md` |
| `apps/backend/tests/extraction/test_pdf_fixtures.py` | `common/extraction/readme.md` |
| `apps/backend/tests/extraction/test_pii_redaction.py` | `docs/agents/red-lines.md` |
| `apps/backend/tests/extraction/test_statement_parsing_supervisor.py` | `common/extraction/readme.md` |
| `apps/backend/tests/extraction/test_statements_supervisor_errors.py` | `common/extraction/readme.md` |
| `apps/backend/tests/infra/test_boot.py` | `common/meta/development.md` |
| `apps/backend/tests/infra/test_config.py` | `common/meta/development.md` |
| `apps/backend/tests/infra/test_database.py` | `common/meta/development.md` |
| `apps/backend/tests/infra/test_migrations.py` | `common/meta/schema.md` |
| `apps/backend/tests/infra/test_rate_limit.py` | `docs/agents/red-lines.md` |
| `apps/backend/tests/infra/test_schema_drift.py` | `common/meta/schema.md` |
| `apps/backend/tests/infra/test_schema_guardrails.py` | `common/meta/schema.md` |
| `apps/backend/tests/pricing/market_data/test_lazy_fx.py` | `common/pricing/contract.py` |
| `apps/backend/tests/reconciliation/test_anomaly_service.py` | `common/reconciliation/reconciliation.md` |
| `apps/backend/tests/reconciliation/test_reconciliation_stats.py` | `common/reconciliation/reconciliation.md` |
| `apps/backend/tests/reporting/test_net_income_average_rates.py` | `common/reporting/reporting.md` |
| `apps/backend/tests/reporting/test_reporting_fx_fallbacks.py` | `common/reporting/reporting.md` |
| `apps/backend/tests/reporting/test_reporting_helpers.py` | `common/reporting/reporting.md` |
| `apps/backend/tests/reporting/test_reporting_layer3.py` | `common/reporting/reporting.md` |
| `apps/backend/tests/reporting/test_reporting_snapshot.py` | `common/reporting/reporting.md` |
| `apps/backend/tests/reporting/test_reports_currencies_and_paths.py` | `common/reporting/reporting.md` |
| `apps/backend/tests/reporting/test_reports_router_additional.py` | `common/reporting/reporting.md` |
| `apps/backend/tests/schemas/test_ai_feedback_schema.py` | `common/llm/ai.md` |
| `apps/backend/tests/schemas/test_audit_schema.py` | `common/meta/schema.md` |
| `apps/backend/tests/schemas/test_user_schema.py` | `common/identity/readme.md` |
| `apps/backend/tests/reporting/test_confidence_tier.py` | `common/audit/readme.md#source-type-trust-hierarchy-provenance` |
| `apps/backend/tests/unit/schemas/test_schemas.py` | `common/meta/schema.md` |
| `apps/backend/tests/unit/services/test_source_type_priority.py` | `common/audit/readme.md#source-type-trust-hierarchy-provenance` |
| `apps/backend/tests/unit/platform/test_exceptions.py` | `common/meta/development.md` |
| `apps/backend/tests/test_factories.py` | `apps/backend/tests/factories.py` |
| `apps/frontend/src/__tests__/analytics.test.tsx` | Frontend analytics tracking (OpenPanel PV) — non-blocking infra, not product behavior |
| `apps/frontend/src/__tests__/confidence.test.ts` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/__tests__/confidenceTrendPage.test.tsx` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/__tests__/ConflictResolutionDialog.test.tsx` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/__tests__/ThemeToggle.test.tsx` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/__tests__/TransactionTable.test.tsx` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/__tests__/allocationChart.test.tsx` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/__tests__/api-urls.test.ts` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/__tests__/api.test.ts` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/__tests__/auth_ssr.test.ts` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/__tests__/detailViewComponents.test.tsx` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/__tests__/firstRunModal.test.tsx` | `common/llm/readme.md` |
| `apps/frontend/src/__tests__/holdingsTable.test.tsx` | `common/portfolio/assets.md` |
| `apps/frontend/src/__tests__/llmApiFunctions.test.ts` | `common/llm/readme.md` |
| `apps/frontend/src/__tests__/llmSettingsPage.test.tsx` | `common/llm/readme.md` |
| `apps/frontend/src/__tests__/performanceCard.test.tsx` | `common/portfolio/assets.md` |
| `apps/frontend/src/__tests__/portfolioPricesPage.test.tsx` | `common/portfolio/assets.md` |
| `apps/frontend/src/__tests__/reportPackage.test.ts` | `apps/frontend/frontend-patterns.md` (#1868 S5 PR-C — pure helpers extracted from usePersonalReportPackage.ts) |
| `apps/frontend/src/__tests__/reviewPages.test.tsx` | `common/extraction/confirmation-workflow.md` |
| `apps/frontend/src/__tests__/reviewQueuePage.actions.test.tsx` | `common/reconciliation/confirmation-workflow.md` |
| `apps/frontend/src/__tests__/reviewQueuePage.coverage.test.tsx` | `common/reconciliation/confirmation-workflow.md` |
| `apps/frontend/src/__tests__/statementReviewPage.coverage.test.tsx` | `common/extraction/confirmation-workflow.md` |
| `apps/frontend/src/__tests__/statusLabels.test.ts` | `apps/frontend/frontend-patterns.md` (#1609 colour-not-alone status labels) |
| `apps/frontend/src/__tests__/sheetAndDetailDialogComponents.test.tsx` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/__tests__/theme.coverage.test.ts` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/__tests__/types.test.ts` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/__tests__/openingBalanceWarningBanner.test.tsx` | `apps/frontend/frontend-patterns.md` (#1486 opening-balance warning surface) |
| `apps/frontend/src/__tests__/useBaseCurrency.test.tsx` | `apps/frontend/frontend-patterns.md` (#1487 base-currency hook) |
| `apps/frontend/src/__tests__/useBodyScrollLock.test.tsx` | `apps/frontend/frontend-patterns.md` (#1608 modal/sheet body-scroll lock) |
| `apps/frontend/src/__tests__/useLlmConfigStatus.test.ts` | `common/llm/readme.md` |
| `apps/frontend/src/components/__tests__/ProcessingSummaryCard.test.tsx` | `common/ledger/readme.md` |
| `apps/frontend/src/components/review/__tests__/ConflictResolutionDialog.keydown.test.tsx` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/components/review/__tests__/TransactionTable.keyEvents.test.tsx` | `apps/frontend/frontend-patterns.md` |
| `apps/frontend/src/hooks/__tests__/useFocusTrap.test.tsx` | `apps/frontend/frontend-patterns.md` |
| `tests/tooling/test_agent_runtime_symlinks.py` | `docs/agents/orchestration.md` |
| `tests/tooling/test_audit_router_contracts.py` | `docs/reference/router-contract-maturity.md` |
| `tests/tooling/test_csp_script_src_contract.py` | `common/testing/ci-cd.md` (#1623 CSP script-src allowlist contract) |
| `tests/tooling/test_required_env_keys_contract.py` | `common/testing/ci-cd.md` (#1623 manifest<->config env-key drift contract) |
| `tests/tooling/test_critical_value_proof_ratchet.py` | `common/testing/ci-cd.md` (#1623 value-asserting ratchet for critical outcomes) |
| `tests/tooling/test_cassette_replay_wired.py` | `common/testing/ci-cd.md` (#1623 lock: cassette-replay net cannot silently skip) |
| `tests/tooling/test_browser_invariant_events_valid.py` | `common/testing/ci-cd.md` (#1623 lock: e2e browser-invariant events stay real, not vacuous) |
| `tests/tooling/test_brokerage_prompt_contract.py` | `common/extraction/readme.md` |
| `tests/tooling/test_check_env_keys.py` | `common/meta/development.md` |
| `tests/tooling/test_check_manifest.py` | `common/meta/data/MANIFEST.yaml` |
| `tests/tooling/test_check_package_contract.py` | `common/meta/readme.md` |
| `tests/tooling/test_check_package_directory_coverage.py` | `common/meta/readme.md` |
| `tests/tooling/test_app_boundary.py` | `common/meta/migration-standard.md` |
| `tests/tooling/test_stage2_residue_closeout.py` | `common/meta/migration-standard.md` |
| `tests/tooling/test_taxonomy_drift.py` | `common/meta/migration-standard.md` |
| `tests/tooling/test_check_ssot_ownership.py` | `common/meta/data/MANIFEST.yaml` |
| `tests/tooling/test_five_layer_model.py` | `common/meta/readme.md` |
| `tests/tooling/test_counter_package.py` | `common/meta/readme.md` |
| `tests/tooling/test_llm_package.py` | `common/meta/readme.md` |
| `tests/tooling/test_extraction_package.py` | `common/meta/readme.md` |
| `tests/tooling/test_identity_package.py` | `common/meta/readme.md` |
| `tests/tooling/test_ledger_package.py` | `common/meta/readme.md` |
| `tests/tooling/test_platform_package.py` | `common/meta/readme.md` |
| `tests/tooling/test_testing_package.py` | `common/meta/readme.md` |
| `tests/tooling/test_pricing_package.py` | `common/meta/readme.md` |
| `tests/tooling/test_portfolio_package.py` | `common/meta/readme.md` |
| `tests/tooling/test_reporting_package.py` | `common/meta/readme.md` |
| `tests/tooling/test_reconciliation_package.py` | `common/meta/readme.md` |
| `apps/backend/tests/reconciliation/test_repository.py` | `common/reconciliation/contract.py` |
| `apps/backend/tests/pricing/test_repository.py` | `common/pricing/contract.py` |
| `apps/backend/tests/pricing/test_manual.py` | `common/pricing/contract.py` |
| `apps/backend/tests/pricing/test_fx.py` | `common/pricing/contract.py` |
| `apps/backend/tests/pricing/test_convert.py` | `common/pricing/contract.py` |
| `apps/backend/tests/pricing/test_resolve.py` | `common/pricing/contract.py` |
| `apps/backend/tests/pricing/test_subject.py` | `common/pricing/contract.py` |
| `apps/backend/tests/pricing/market_data/__init__.py` | Package marker |
| `tests/tooling/test_coverage_analyzer.py` | `common/testing/coverage.md` |
| `tests/tooling/test_migration_safety_gates.py` | `common/meta/readme.md` |
| `tests/tooling/test_delivery_gates_contract.py` | `common/meta/data/delivery-gates.yaml` |
| `tests/tooling/test_env_contract_boundary.py` | `common/observability/observability.md`, `common/runtime/environments.md` |
| `tests/tooling/test_github_workflow_timing_summary.py` | `common/testing/ci-cd.md` |
| `tests/tooling/test_infra2_pin_is_release_tag.py` | `common/runtime/deployment.md` |
| `tests/tooling/test_merge_lcov.py` | `common/testing/coverage.md` |
| `tests/tooling/test_preflight.py` | `common/testing/ci-cd.md` |
| `tests/tooling/test_seed_fx_rates.py` | `common/pricing/market_data.md` |
| `tests/tooling/test_validate_schemas.py` | `common/meta/schema.md` |
| `tests/tooling/test_extraction_pii_mask.py` | `common/llm/readme.md#cassette-graded-eval` |
| `tests/tooling/test_record_hf_cassettes.py` | `common/llm/readme.md#cassette-graded-eval` |

## Source Direct-Test Heuristic Exceptions

The following source files do not have direct filename-matched tests. They are
not unowned product behavior; they are support code or are tested through page,
router, or generated-fixture flows.

| Source path | Classification |
|---|---|
| `apps/backend/src/observability/error_ids.py` | Shared error-code constants; covered indirectly by exception/API tests |
| `apps/backend/src/routers/user_settings.py` | Owned by AC18.5.5 through `apps/backend/tests/api/test_user_settings_router.py` |
| `apps/frontend/src/components/review/BalanceIndicator.tsx` | Review UI subcomponent covered through review page/component suites |
| `apps/frontend/src/components/review/ReviewActionBar.tsx` | Review UI subcomponent covered through review page/action suites |
| `apps/frontend/src/components/review/Stage2ReviewQueue.tsx` | Review UI subcomponent covered through review queue and run review page suites |
| `common/testing/fixtures/pdf/generators/base_generator.py` | EPIC-009 fixture infrastructure covered by `tests/tooling/test_pdf_fixture_epic009_behavior.py` |
| `common/testing/fixtures/pdf/generators/font_utils.py` | EPIC-009 fixture infrastructure covered by `tests/tooling/test_pdf_fixture_tooling_coverage.py` |

### Staging Bug Regression Repros

Regression guards for production bugs found during real-machine testing. They
pin a specific fix rather than owning an EPIC acceptance criterion.

| Path | Owner |
|---|---|
| `apps/backend/tests/repro/test_reports_500_market_data.py` | Issue #1388 (reports must not 500 on best-effort market-data sync failure) |
| `apps/backend/tests/repro/test_brokerage_identifier.py` | Issue #1389 (brokerage position identifier must prefer ticker over company name) |
| `apps/backend/tests/repro/test_balance_validation_vacuous.py` | Issue #1390 (balance validation must not pass vacuously with no closing balance) |
| `apps/backend/tests/repro/test_review_document_url.py` | Issue #1391 (Stage-1 review PDF URL must use the public endpoint) |
| `apps/backend/tests/portfolio/test_brokerage_import_gated_on_review.py` | Issue #1408 (brokerage positions must not count toward holdings/net-worth before review) |
| `apps/backend/tests/portfolio/test_position_valuation_consistency.py` | Issue #1098 (unified position valuation — native+base reconcile) |

## Rule

New tests for user-visible behavior must include an AC reference. New helper,
fixture, or pure contract tests without AC references must be added to this file
in the same PR, with an SSOT or EPIC owner. Product E2E tests under
`tests/e2e/test_*.py` or `apps/backend/tests/e2e/test_*.py` are not eligible
for this allow-list; attach AC IDs or remove the obsolete test. This policy is
enforced by `tools/lint_doc_consistency.py`.

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
| `apps/backend/tests/accounting/_ledger_helpers.py` | Shared accounting ledger invariant test helper |
| `apps/backend/tests/ai/__init__.py` | Package marker |
| `apps/backend/tests/assets/__init__.py` | Package marker |
| `apps/backend/tests/auth/__init__.py` | Package marker |
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
| `tests/tooling/__init__.py` | Package marker |
| `tests/tooling/conftest.py` | Shared tooling-test fixtures |
| `tests/e2e/conftest.py` | Shared top-level E2E fixtures |
| `apps/backend/tests/unit/conftest.py` | Shared unit fixtures |
| `apps/frontend/src/__tests__/helpers/renderReviewComponent.tsx` | Shared frontend render helper |

### SSOT Or Code-Contract Hardening Tests

These files are real tests, but they protect cross-cutting contracts rather
than owning EPIC acceptance criteria. They are not AC proof until an EPIC adds
explicit AC IDs for the behavior.

| Path | Owner |
|---|---|
| `apps/backend/tests/accounting/test_money.py` | `docs/ssot/accounting.md` |
| `apps/backend/tests/accounting/test_processing_account_endpoints.py` | `docs/ssot/processing_account.md` |
| `apps/backend/tests/api/test_ai_feedback_router_extra.py` | `docs/ssot/ai.md` |
| `apps/backend/tests/assets/test_assets_positions_and_depreciation.py` | `docs/ssot/assets.md` |
| `apps/backend/tests/auth/test_auth_router_unit.py` | `docs/ssot/auth.md` |
| `apps/backend/tests/extraction/test_account_last4_defense.py` | `docs/ssot/extraction.md` |
| `apps/backend/tests/extraction/test_classification_service.py` | `docs/ssot/extraction.md` |
| `apps/backend/tests/extraction/test_extraction_cassette_replay.py` | `docs/ssot/llm.md` (EPIC-023 AC23.6 streaming-bridge scaffold; skipped via `needs_real_cassette` until real cassettes are recorded with `make llm-record`, then it becomes AC proof) |
| `apps/backend/tests/extraction/test_dual_write_layer2.py` | `docs/ssot/extraction.md` |
| `apps/backend/tests/extraction/test_extraction_logging.py` | `docs/ssot/extraction.md` |
| `apps/backend/tests/extraction/test_pdf_fixtures.py` | `docs/ssot/extraction.md` |
| `apps/backend/tests/extraction/test_pii_redaction.py` | `docs/agents/red-lines.md` |
| `apps/backend/tests/extraction/test_statement_parsing_supervisor.py` | `docs/ssot/extraction.md` |
| `apps/backend/tests/extraction/test_statements_supervisor_errors.py` | `docs/ssot/extraction.md` |
| `apps/backend/tests/infra/test_boot.py` | `docs/ssot/development.md` |
| `apps/backend/tests/infra/test_config.py` | `docs/ssot/development.md` |
| `apps/backend/tests/infra/test_database.py` | `docs/ssot/development.md` |
| `apps/backend/tests/infra/test_migrations.py` | `docs/ssot/schema.md` |
| `apps/backend/tests/infra/test_rate_limit.py` | `docs/agents/red-lines.md` |
| `apps/backend/tests/infra/test_schema_drift.py` | `docs/ssot/schema.md` |
| `apps/backend/tests/infra/test_schema_guardrails.py` | `docs/ssot/schema.md` |
| `apps/backend/tests/market_data/test_fx.py` | `docs/ssot/market_data.md` |
| `apps/backend/tests/reconciliation/test_anomaly_service.py` | `docs/ssot/reconciliation.md` |
| `apps/backend/tests/reconciliation/test_reconciliation_stats.py` | `docs/ssot/reconciliation.md` |
| `apps/backend/tests/reporting/test_fx_average_rate_fallback.py` | `docs/ssot/reporting.md` |
| `apps/backend/tests/reporting/test_net_income_average_rates.py` | `docs/ssot/reporting.md` |
| `apps/backend/tests/reporting/test_reporting_fx_fallbacks.py` | `docs/ssot/reporting.md` |
| `apps/backend/tests/reporting/test_reporting_helpers.py` | `docs/ssot/reporting.md` |
| `apps/backend/tests/reporting/test_reporting_layer3.py` | `docs/ssot/reporting.md` |
| `apps/backend/tests/reporting/test_reporting_snapshot.py` | `docs/ssot/reporting.md` |
| `apps/backend/tests/reporting/test_reports_currencies_and_paths.py` | `docs/ssot/reporting.md` |
| `apps/backend/tests/reporting/test_reports_router_additional.py` | `docs/ssot/reporting.md` |
| `apps/backend/tests/schemas/test_ai_feedback_schema.py` | `docs/ssot/ai.md` |
| `apps/backend/tests/schemas/test_audit_schema.py` | `docs/ssot/schema.md` |
| `apps/backend/tests/schemas/test_user_schema.py` | `docs/ssot/auth.md` |
| `apps/backend/tests/services/test_confidence_tier.py` | `docs/ssot/source-type-priority.md` |
| `apps/backend/tests/unit/schemas/test_schemas.py` | `docs/ssot/schema.md` |
| `apps/backend/tests/unit/services/test_source_type_priority.py` | `docs/ssot/source-type-priority.md` |
| `apps/backend/tests/unit/utils/test_exceptions.py` | `docs/ssot/development.md` |
| `apps/backend/tests/test_factories.py` | `apps/backend/tests/factories.py` |
| `apps/frontend/src/__tests__/analytics.test.tsx` | Frontend analytics tracking (OpenPanel PV) — non-blocking infra, not product behavior |
| `apps/frontend/src/__tests__/confidence.test.ts` | `docs/ssot/frontend-patterns.md` |
| `apps/frontend/src/__tests__/confidenceTrendPage.test.tsx` | `docs/ssot/frontend-patterns.md` |
| `apps/frontend/src/__tests__/ConflictResolutionDialog.test.tsx` | `docs/ssot/frontend-patterns.md` |
| `apps/frontend/src/__tests__/ThemeToggle.test.tsx` | `docs/ssot/frontend-patterns.md` |
| `apps/frontend/src/__tests__/TransactionTable.test.tsx` | `docs/ssot/frontend-patterns.md` |
| `apps/frontend/src/__tests__/allocationChart.test.tsx` | `docs/ssot/frontend-patterns.md` |
| `apps/frontend/src/__tests__/api-urls.test.ts` | `docs/ssot/frontend-patterns.md` |
| `apps/frontend/src/__tests__/api.test.ts` | `docs/ssot/frontend-patterns.md` |
| `apps/frontend/src/__tests__/auth_ssr.test.ts` | `docs/ssot/auth.md` |
| `apps/frontend/src/__tests__/detailViewComponents.test.tsx` | `docs/ssot/frontend-patterns.md` |
| `apps/frontend/src/__tests__/firstRunModal.test.tsx` | `docs/ssot/llm.md` |
| `apps/frontend/src/__tests__/holdingsTable.test.tsx` | `docs/ssot/assets.md` |
| `apps/frontend/src/__tests__/llmApiFunctions.test.ts` | `docs/ssot/llm.md` |
| `apps/frontend/src/__tests__/llmSettingsPage.test.tsx` | `docs/ssot/llm.md` |
| `apps/frontend/src/__tests__/performanceCard.test.tsx` | `docs/ssot/assets.md` |
| `apps/frontend/src/__tests__/portfolioPricesPage.test.tsx` | `docs/ssot/assets.md` |
| `apps/frontend/src/__tests__/reviewPages.test.tsx` | `docs/ssot/confirmation-workflow.md` |
| `apps/frontend/src/__tests__/reviewQueuePage.actions.test.tsx` | `docs/ssot/confirmation-workflow.md` |
| `apps/frontend/src/__tests__/reviewQueuePage.coverage.test.tsx` | `docs/ssot/confirmation-workflow.md` |
| `apps/frontend/src/__tests__/statementReviewPage.coverage.test.tsx` | `docs/ssot/confirmation-workflow.md` |
| `apps/frontend/src/__tests__/sheetAndDetailDialogComponents.test.tsx` | `docs/ssot/frontend-patterns.md` |
| `apps/frontend/src/__tests__/theme.coverage.test.ts` | `docs/ssot/frontend-patterns.md` |
| `apps/frontend/src/__tests__/types.test.ts` | `docs/ssot/frontend-patterns.md` |
| `apps/frontend/src/__tests__/useLlmConfigStatus.test.ts` | `docs/ssot/llm.md` |
| `apps/frontend/src/components/__tests__/ProcessingSummaryCard.test.tsx` | `docs/ssot/processing_account.md` |
| `apps/frontend/src/components/review/__tests__/ConflictResolutionDialog.keydown.test.tsx` | `docs/ssot/frontend-patterns.md` |
| `apps/frontend/src/components/review/__tests__/TransactionTable.keyEvents.test.tsx` | `docs/ssot/frontend-patterns.md` |
| `apps/frontend/src/hooks/__tests__/useFocusTrap.test.tsx` | `docs/ssot/frontend-patterns.md` |
| `tests/tooling/test_agent_runtime_symlinks.py` | `docs/agents/orchestration.md` |
| `tests/tooling/test_audit_router_contracts.py` | `docs/reference/router-contract-maturity.md` |
| `tests/tooling/test_brokerage_prompt_contract.py` | `docs/ssot/extraction.md` |
| `tests/tooling/test_check_env_keys.py` | `docs/ssot/development.md` |
| `tests/tooling/test_check_manifest.py` | `docs/ssot/MANIFEST.yaml` |
| `tests/tooling/test_check_package_contract.py` | `common/governance/readme.md` |
| `tests/tooling/test_check_ssot_ownership.py` | `docs/ssot/MANIFEST.yaml` |
| `tests/tooling/test_counter_package.py` | `common/governance/readme.md` |
| `tests/tooling/test_coverage_analyzer.py` | `docs/ssot/coverage.md` |
| `tests/tooling/test_migration_safety_gates.py` | `docs/ssot/authority-tiers.md` |
| `tests/tooling/test_delivery_gates_contract.py` | `docs/ssot/delivery-gates.yaml` |
| `tests/tooling/test_dokploy_failure_snapshot.py` | `docs/ssot/ci-cd.md` |
| `tests/tooling/test_env_contract_boundary.py` | `docs/ssot/observability.md`, `docs/ssot/environments.md` |
| `tests/tooling/test_generate_fixtures.py` | `docs/ssot/extraction.md` |
| `tests/tooling/test_github_workflow_timing_summary.py` | `docs/ssot/ci-cd.md` |
| `tests/tooling/test_merge_lcov.py` | `docs/ssot/coverage.md` |
| `tests/tooling/test_preflight.py` | `docs/ssot/ci-cd.md` |
| `tests/tooling/test_sanitize_fixtures.py` | `docs/agents/red-lines.md` |
| `tests/tooling/test_seed_fx_rates.py` | `docs/ssot/market_data.md` |
| `tests/tooling/test_validate_schemas.py` | `docs/ssot/schema.md` |

## Source Direct-Test Heuristic Exceptions

The following source files do not have direct filename-matched tests. They are
not unowned product behavior; they are support code or are tested through page,
router, or generated-fixture flows.

| Source path | Classification |
|---|---|
| `apps/backend/src/constants/error_ids.py` | Shared error-code constants; covered indirectly by exception/API tests |
| `apps/backend/src/routers/user_settings.py` | Owned by AC18.5.5 through `apps/backend/tests/api/test_user_settings_router.py` |
| `apps/frontend/src/components/review/BalanceIndicator.tsx` | Review UI subcomponent covered through review page/component suites |
| `apps/frontend/src/components/review/ReviewActionBar.tsx` | Review UI subcomponent covered through review page/action suites |
| `apps/frontend/src/components/review/Stage2ReviewQueue.tsx` | Review UI subcomponent covered through review queue and run review page suites |
| `tools/_lib/pdf_fixtures/generators/base_generator.py` | EPIC-009 fixture infrastructure covered by `tests/tooling/test_pdf_fixture_epic009_behavior.py` |
| `tools/_lib/pdf_fixtures/generators/font_utils.py` | EPIC-009 fixture infrastructure covered by `tests/tooling/test_pdf_fixture_tooling_coverage.py` |

### Staging Bug Regression Repros

Regression guards for production bugs found during real-machine testing. They
pin a specific fix rather than owning an EPIC acceptance criterion.

| Path | Owner |
|---|---|
| `apps/backend/tests/repro/test_reports_500_market_data.py` | Issue #1388 (reports must not 500 on best-effort market-data sync failure) |

## Rule

New tests for user-visible behavior must include an AC reference. New helper,
fixture, or pure contract tests without AC references must be added to this file
in the same PR, with an SSOT or EPIC owner. Product E2E tests under
`tests/e2e/test_*.py` or `apps/backend/tests/e2e/test_*.py` are not eligible
for this allow-list; attach AC IDs or remove the obsolete test. This policy is
enforced by `tools/lint_doc_consistency.py`.

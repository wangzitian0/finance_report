# EPIC-008: Comprehensive Testing Strategy (Smoke & E2E)

> **Status**: ✅ Core Complete
> **Vision Anchor**: `decision-filter-accuracy-auditability`
> **Owner**: QA / DevOps
> **Date**: 2026-01-16
> **Updated**: 2026-06-10

## 1. Overview

This epic defines the strategy for **Smoke Testing** and **End-to-End (E2E) Testing** to ensure system stability across environments. The focus is on **vertical, scenario-based flows** that mimic real user behavior, moving away from isolated functional checks.

## Macro Proof Ownership

- `personal-financial-report-package`
- `asset-distribution-net-worth`
- `monthly-income-spending`
- `investment-performance`
- `source-ledger-report-traceability`

## 2. Testing Strategy

### 2.1 Smoke Tests (Health Checks)

**Goal**: Verify that the critical paths of the application are up and running after deployment.
**Frequency**: On every deployment to any environment.

| Environment | Scope | Data Mode | Constraint |
|-------------|-------|-----------|------------|
| **Development** | Full CRUD | Write Allowed | Test data is reset/cleaned up. |
| **Staging** | Full CRUD | Write Allowed | Mimics production data volume. |
| **Production** | **Read-Only** | **Safe Mode** | No writes. Check system status, read public/safe endpoints, verify static assets. |

### 2.2 End-to-End (E2E) Tests

**Goal**: Validate full user journeys from UI to Database.
**Frequency**: Nightly or Pre-release.
**Target Environment**: **Staging Only**.
**Tooling**: Playwright (Browser-based verification).

> **Note**: E2E tests are expensive and flaky. We run them on Staging to avoid polluting Production and to ensure stability before release.

### 2.3 Coverage Tier Definition

E2E coverage is measured across three tiers of increasing fidelity:

| Tier | Method | Transport | Environment | What It Proves |
|------|--------|-----------|-------------|----------------|
| **Tier 1** | API Integration E2E | `AsyncClient` + `ASGITransport` (in-process) | CI (pytest, real DB) | Router→Service→DB→Response contract works |
| **Tier 2** | HTTP E2E | `httpx` against deployed app | PR / Staging | Real HTTP, real network, real deployment |
| **Tier 3** | Browser E2E | Playwright | Staging | Full UI→API→DB user journey |

**Coverage accounting rules:**
- An AC counts as "covered" for traceability when it has a qualifying real test
  reference in a CI-required execution stage, not a mock/stub placeholder.
- Tier 2/3 tests that `skip` due to missing env vars (e.g., `FRONTEND_URL`) do
  not count toward mandatory proof unless they are mapped to a required CI stage
  and run under that stage's strict gate.
- The AC coverage rate is generated from registry and test references; it is not
  a line-coverage percentage and not a replacement for CI pass/fail status.
- CI source coverage uses the shared coverage policy in `common/coverage/policy.py`. New backend, frontend, common, and tools modules are expected to appear in the matching LCOV report unless the policy explicitly excludes them.
  The AC8.13.x requirement definitions and proof mappings are maintained in
  the Test Cases table below, not duplicated in this strategy overview.

### 2.3.1 Test Stage Semantics and Left-Move Plan (Unit / Integration / E2E)

Integration tests and E2E tests are intentionally different in this project:

- **Integration (marker-level, backend)**: multiple backend service/modules participate, usually with real infrastructure (DB/storage/config), but no browser path.
- **E2E (behavioral)**: requirement-level behavior is proven end-to-end from API contract or real browser workflow.

### Coverage and Proof Semantics by Stage

| Stage | Scope | CI execution now | Coverage / proof semantics |
|---|---|---|---|
| Unit (Fast/Shard) | Backend tests excluding `slow`, `e2e`, and `integration` markers | Required on `main`/heavy PR after integration/Tier-1 gates pass: `backend` job, 5-way shard, `-m "not slow and not e2e and not integration"` | Contributes to unified line coverage (backend part), AC traceability generation, and baseline no-regression gate |
| Integration (backend) | Backend tests marked `integration` | Explicit CI stage: `backend-integration` job, marker-scoped and service-backed | Not included in unified coverage by default; AC proof channel only |
| Tier 1 API E2E (`-m e2e`) | `apps/backend/tests/e2e/test_core_journeys.py` ASGI/API contract flows | Explicit CI stage: `backend-e2e-tier1` job with marker override and explicit Tier-1 scope | Behavioral proof for ACs and regression risk; **not included in unified line coverage** |
| Frontend Playwright | Provider-free specs under `apps/frontend/playwright` | Explicit CI stage inside the `frontend` job after build and Vitest; env-gated specs are not required proof | Browser UI behavioral proof only, not part of unified line coverage |
| Tier 2 HTTP E2E | Deploy-aware HTTP-level flows through `tools/tier2_http_e2e.py` | Staging deploy after shell smoke and before broader deployed E2E | Behavioral proof only, not part of unified line coverage |
| Tier 3 Browser E2E | `tests/e2e` Playwright/browser scenarios | Post-merge staging/prod gates and PR preview where appropriate | Behavioral proof only; AC pass rate requires real pass (skip and stub-only do not count) |

### Stage-by-Stage Semantics

| Metric | Definition | Data source | Regression gate behavior |
|---|---|---|---|
| Unified Line Coverage | `(sum covered LF) / (sum executable LF)` over unified files only | `coverage/backend.lcov`, `coverage/frontend.lcov`, `coverage/common.lcov`, `coverage/tools.lcov` after policy mapping | No-regression vs `unified-coverage.json`; line-based only |
| AC Pass Rate | `(ACs with at least one passing qualifying test) / (Total ACs)` | Generated AC coverage audit report | Informational for behavior completeness; not a line-coverage substitute |
| AC Traceability Gate | Real AC references in CI-required execution stages | `tools/check_ac_index.py`, `docs/ssot/test-execution-matrix.yaml`, `tools/check_e2e_epic_traceability.py` | Fail closed when mandatory AC is missing, stub-only, placeholder-only, or real-only outside required execution |

AC rates are generated on each CI run from `python tools/analyze_test_ac_coverage.py` inputs and do not mean line coverage. If a number changes, it is an AC definition or behavior-proof change, not automatically a line-coverage baseline change.

Current test and AC coverage status is generated, not hand-maintained here.
Use `python tools/analyze_test_ac_coverage.py --no-write --stdout`,
`python tools/audit_ac_epic_mismatches.py`, and CI artifacts for live proof
counts.

### 2.3.2 E2E EPIC Traceability

Every `test_*` function under product E2E roots must carry at least one
`EPIC-xxx` ID in the test function name or function docstring. Every
`docs/project/EPIC-*.md` file must be owned by at least one product E2E test
function. The CI traceability gate enforces this with
`tools/check_e2e_epic_traceability.py` before generating traceability artifacts.
The same gate validates the root README EPIC map against the project EPIC file
set, and scans E2E-like test assets so files outside product E2E roots are
either explicitly classified as non-product infra/submodule assets or fail CI.

### 2.4 Synthetic Test Data (PDF Generation)

To ensure deterministic and controllable tests for Phase 3 (Import/Parsing), we utilize a synthetic data generation script.

- **Source**: `tools/generate_pdf_fixtures.py`
- **Output**: Generates valid PDF bank statements (DBS/Citi style) with known transaction sets.
- **Purpose**: Validates the *pipeline* (Upload -> Parse -> Reconcile) works, without relying on unstable external OCR accuracy or PII-laden real documents.
- **Scope Limitation**: OCR/Parsing *accuracy* benchmarks are handled in a separate Epic. This Epic focuses on flow functional correctness.

---

## 3. Core Proof Paths

The old hand-written 100-scenario checklist was removed from this EPIC because
it duplicated executable E2E tests and drifted from CI execution. Current macro
proof is managed by:

| Proof layer | Owner |
|---|---|
| README macro outcomes and owner EPIC declarations | `README.md`, EPIC `Macro Proof Ownership` sections |
| Critical E2E proof paths | `tools/check_ac_index.py` (derived view of [critical-proof-outcomes.yaml](../ssot/critical-proof-outcomes.yaml)) |
| Product E2E function ownership | `tools/check_e2e_epic_traceability.py` |
| AC proof and placeholder/stub exclusion | `tools/check_ac_index.py`, CI traceability artifact |

New scenario coverage must be added as ACs plus tests or as critical proof
matrix rows, not as another prose scenario checklist.

## 4. Implementation Notes

### 4.1 Tools
- **Backend**: `pytest` for Integration/Unit.
- **Frontend/E2E**: `Playwright` (TypeScript).
- **Smoke**: Custom Python script or simple `curl`/`httpie` sequence.
- **Test Data**: `tools/generate_pdf_fixtures.py` (ReportLab) for generating PDF inputs.

### 4.2 CI/CD Integration

CI execution shape is owned by [ci-cd.md](../ssot/ci-cd.md), workflows, and
[test-execution-matrix.yaml](../ssot/test-execution-matrix.yaml). Do not copy
job inventories or scenario counts into this EPIC.

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/e2e/` and `tools/smoke_test.sh`
>
> ℹ️ **Non-contiguous AC numbering**: Gaps in `AC8.x.y` numbers reflect deprecated or merged ACs preserved for historical traceability through generated registry indexes plus explicit overrides. Do **not** renumber. New active ACs append to the next available index in the owning EPIC block.

### AC8.1: Smoke Tests (Health Checks) — migrated to the `runtime` package

> The smoke-test / health-check ACs (were `AC8.1.*`) moved into the
> `runtime` package roadmap (`common/runtime/contract.py`) under the
> package-scoped `AC-runtime.<group>.<seq>` id scheme —
> `generate_ac_registry.py` reads package-contract roadmaps. Migrated ids
> (homed in the package roadmap): `AC-runtime.1.1` · `AC-runtime.1.2` ·
> `AC-runtime.1.3` · `AC-runtime.1.4`. `runtime` owns the environment smoke test
> (`common/runtime/readme.md`).

### AC8.2: Phase 1 - Onboarding & Account Structure

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.2.1 | New User Registration | `test_register_and_login_flow()` | `e2e/test_core_journeys.py` | P0 |
| AC8.2.2 | Create Cash Account | `test_create_cash_account()` | `e2e/test_core_journeys.py` | P0 |
| AC8.2.3 | Create Bank Account | `test_create_bank_account()` | `e2e/test_core_journeys.py` | P0 |
| AC8.2.4 | Update account | `test_update_account()` | `e2e/test_core_journeys.py` | P1 |
| AC8.2.5 | Delete account | `test_delete_account()` | `e2e/test_core_journeys.py` | P1 |

### AC8.3: Phase 2 - Manual Journal Entries

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.3.1 | Simple Expense Entry | `test_simple_expense_entry()` | `e2e/test_core_journeys.py` | P0 |
| AC8.3.2 | Void Entry | `test_void_journal_entry()` | `e2e/test_core_journeys.py` | P0 |
| AC8.3.3 | Post Draft Entry | `test_post_draft_entry()` | `e2e/test_core_journeys.py` | P0 |
| AC8.3.4 | Unbalanced Entry Rejected | `test_unbalanced_journal_entry_rejection()` | `e2e/test_core_journeys.py` | P0 |
| AC8.3.5 | Journal Entry CRUD | `test_journal_entry_crud()` | `e2e/test_core_journeys.py` | P1 |

### AC8.4: Phase 3 - Statement Import & Parsing

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.4.1 | Statement upload (CSV) | `test_statement_upload_csv()` | `e2e/test_core_journeys.py` | P0 |
| AC8.4.2 | Statement list and get | `test_statement_list_and_get()` | `e2e/test_core_journeys.py` | P0 |
| AC8.4.3 | Statement full flow | `test_statement_full_flow()` | `e2e/test_core_journeys.py` | P0 |

### AC8.5: Phase 4 - Reconciliation Engine

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.5.1 | Reconciliation engine runs | `test_reconciliation_engine_runs()` | `e2e/test_core_journeys.py` | P0 |
| AC8.5.2 | Reconciliation stats endpoint | `test_reconciliation_stats()` | `e2e/test_core_journeys.py` | P1 |
| AC8.5.3 | Match acceptance | `test_reconciliation_match_acceptance()` | `e2e/test_core_journeys.py` | P1 |

### AC8.6: Phase 5 - Reporting & Visualization

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.6.1 | View Balance Sheet | `test_balance_sheet_report()` | `e2e/test_core_journeys.py` | P0 |
| AC8.6.2 | View Income Statement | `test_income_statement_report()` | `e2e/test_core_journeys.py` | P0 |
| AC8.6.3 | View Cash Flow Report | `test_cash_flow_report()` | `e2e/test_core_journeys.py` | P0 |
| AC8.6.4 | Report navigation (all endpoints) | `test_report_navigation_all_endpoints()` | `e2e/test_core_journeys.py` | P1 |

### AC8.7: API Authentication & Authorization

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.7.1 | API authentication failures | `test_api_authentication_failures()` | `e2e/test_core_journeys.py` | P0 |
| AC8.7.2 | Unauthorized access blocked | `test_unauthorized_access_blocked()` | `e2e/test_core_journeys.py` | P0 |
| AC8.7.3 | User session management | `test_user_session_management()` | `e2e/test_core_journeys.py` | P1 |

### AC8.8: Core E2E Journey Tests

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.8.1 | API health check | `test_api_health_check()` | `e2e/test_core_journeys.py` | P0 |
| AC8.8.2 | Accounts CRUD API | `test_accounts_crud_api()` | `e2e/test_core_journeys.py` | P0 |
| AC8.8.3 | Journal entry lifecycle API | `test_journal_entry_crud()` | `e2e/test_core_journeys.py` | P0 |
| AC8.8.4 | Reports API | `test_balance_sheet_report()` | `e2e/test_core_journeys.py` | P0 |
| AC8.8.5 | Reconciliation API | `test_reconciliation_engine_runs()` | `e2e/test_core_journeys.py` | P0 |

### AC8.9: CI/CD Integration Tests

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.9.1 | PR workflow runs E2E tests | `test_pr_workflow_runs_e2e_tests()` | `e2e/test_core_journeys.py` | P0 |
| AC8.9.2 | Smoke tests integrated | `test_smoke_tests_integrated()` | `e2e/test_core_journeys.py` | P0 |
| AC8.9.3 | Critical test check | `test_critical_test_check_in_workflow()` | `e2e/test_core_journeys.py` | P0 |
| AC8.9.4 | Environment isolation | `test_environment_isolation()` | `e2e/test_core_journeys.py` | P0 |

### AC8.10: Must-Have Scenario Traceability

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC8.10.1 | Health endpoint reachable | `test_traceability_health_endpoint()` | `e2e/test_core_journeys.py` | P0 |
| AC8.10.2 | User can create account | `test_traceability_user_can_create_account()` | `e2e/test_core_journeys.py` | P0 |
| AC8.10.3 | User can create journal entry | `test_traceability_user_can_create_journal_entry()` | `e2e/test_core_journeys.py` | P0 |
| AC8.10.4 | Statement upload triggers AI | `test_statement_upload_csv()` | `e2e/test_core_journeys.py` | P0 |
| AC8.10.5 | Reconciliation engine runs | `test_traceability_reconciliation_engine()` | `e2e/test_core_journeys.py` | P0 |
| AC8.10.6 | Unbalanced entry rejected | `test_traceability_unbalanced_entry_rejected()` | `e2e/test_core_journeys.py` | P0 |
| AC8.10.7 | Reports API accessible | `test_traceability_reports_api()` | `e2e/test_core_journeys.py` | P0 |
| AC8.10.8 | User registration flow | `test_traceability_user_registration()`, `test_registration_flow`, `test_AC8_10_8_registration_flow_accepts_current_landing_route` | `e2e/test_core_journeys.py`, `tests/e2e/test_e2e_flows.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.10.9 | Authentication validation | `test_traceability_authentication_validation()` | `e2e/test_core_journeys.py` | P0 |

### AC8.11: Phase 2 — Core Financial Journeys

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.11.1 | Income Recording | `test_income_recording()` | `e2e/test_core_journeys.py` | P0 |
| AC8.11.2 | Credit Card Spend | `test_credit_card_spend()` | `e2e/test_core_journeys.py` | P0 |
| AC8.11.3 | Credit Card Repayment | `test_credit_card_repayment()` | `e2e/test_core_journeys.py` | P0 |
| AC8.11.4 | Internal Transfer | `test_internal_transfer()` | `e2e/test_core_journeys.py` | P0 |
| AC8.11.5 | Split Transaction | `test_split_transaction()` | `e2e/test_core_journeys.py` | P0 |

### AC8.12: Provider Error-Path Unit Gates

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.12.6 | OCR/vision provider fallback, timeout, and empty-response errors are deterministic | `test_extract_financial_data_shared_ocr_vision_skips_layout_parser`, `test_extract_financial_data_dedicated_ocr_failure_falls_back_to_vision` | `apps/backend/tests/extraction/test_extraction_error_paths.py` | P1 |
| AC8.12.1 | Liability accounts return -net_balance so coverage hits else branch. | `test_returns_negated_balance_for_liability_account` | `reporting/test_fx_revaluation.py` | P1 |
| AC8.12.2 | SQLAlchemyError on flush is wrapped in RevaluationError. | `test_flush_error_raises_revaluation_error` | `reporting/test_fx_revaluation.py` | P1 |
| AC8.12.3 | Accounts that return None from calculate_unrealized_fx_for_account are skipped. | `test_none_revaluation_skipped` | `reporting/test_fx_revaluation.py` | P1 |
| AC8.12.4 | PDF with private URL logs warning and raises ExtractionError (lines 393->403, 416->426). | `test_extract_financial_data_pdf_private_url_raises` | `extraction/test_extraction_error_paths.py` | P1 |
| AC8.12.5 | Image with private URL logs warning and raises ExtractionError (else branch 416->426). | `test_extract_financial_data_image_private_url_raises` | `extraction/test_extraction_error_paths.py` | P1 |

### AC8.13: Tier 3 Browser E2E — Full Statement Journey

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.13.1 | DBS PDF upload → appears in list | `test_dbs_statement_full_journey` | `tests/e2e/test_statement_full_journey.py` | P0 |
| AC8.13.2 | Polling → parsed status visible | `test_dbs_statement_full_journey` | `tests/e2e/test_statement_full_journey.py` | P0 |
| AC8.13.3 | Detail page shows transactions | `test_dbs_statement_full_journey` | `tests/e2e/test_statement_full_journey.py` | P0 |
| AC8.13.4 | Approve → status badge updates in-place on /statements/{id} (no redirect) | `test_dbs_statement_full_journey` | `tests/e2e/test_statement_full_journey.py` | P0 |
| AC8.13.5 | Balance sheet report loads | `test_dbs_statement_full_journey` | `tests/e2e/test_statement_full_journey.py` | P0 |
| AC8.13.6 | Critical staging E2E skips fail the deploy gate | `pytest_runtest_makereport` | `tests/e2e/conftest.py` | P0 |
| AC8.13.7 | Strict full statement journey fails on rejected AI/OCR parsing | `test_dbs_statement_full_journey` | `tests/e2e/test_statement_full_journey.py` | P0 |
| AC8.13.8 | Strict upload readiness E2E does not accept rejected statements | `test_statement_upload_full_flow` | `tests/e2e/test_statement_upload_e2e.py` | P0 |
| AC8.13.9 | Production release runs prod-safe read-only E2E smoke | `test_production_*` | `tests/e2e/test_production_readonly_smoke.py` | P0 |
| AC8.13.10 | Multi-brokerage PDF upload → position import → latest portfolio value | `test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value`, `test_statement_import_flows_to_holdings_and_balance_sheet`, `test_parse_document_routes_brokerage_balance_mismatch_to_parsed`, `test_parse_document_backfills_generated_brokerage_positions_from_pdf_text`, `test_pdf_text_fallback_closes_pymupdf_document` | `tests/e2e/test_brokerage_upload_to_portfolio_value.py`, `apps/backend/tests/portfolio/test_brokerage_position_parsing.py`, `apps/backend/tests/extraction/test_statement_brokerage_import_bridge.py`, `apps/backend/tests/unit/services/test_brokerage_generated_fallback.py` | P0 |
| AC8.13.11 | Staging health check diagnoses API route 404 with route probes | `test_AC8_13_11_health_check_diagnoses_staging_api_route_404` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.12 | AI/OCR gate failures include statement validation context | `test_AC8_13_12_ai_ocr_gate_failure_includes_statement_context` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.13 | Staging deploy uses workflow-level singleton concurrency plus an in-job FIFO guard to prevent duplicate concurrent staging mutation and bounds E2E gate duration with phase timing logs | `test_AC8_13_13_staging_deploy_fast_fail_guardrails`, `test_AC8_13_13_post_merge_train_waits_only_for_older_active_runs` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.14 | Provider-backed staging AI/OCR gate runs separately from deploy health | `test_AC8_13_14_staging_ai_ocr_gate_is_separate_deploy_job` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.15 | Unified coverage policy keeps CI source tree, LCOV reports, and Coveralls uploads aligned | `test_*coverage_policy*` / `test_build_unified_lcov*` | `tests/tooling/` | P0 |
| AC8.13.16 | CI change classification skips backend/frontend/coverage for lightweight changes and uses deterministic npm cache | `test_AC8_13_16_ci_change_classification_and_frontend_cache` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.17 | AC registry generation writes small generated indexes, materializes entries from EPIC docs plus explicit overrides, and preserves no duplicate feature/infra ownership | `test_main_appends_missing_ac_without_rewriting_current_epic_text` / `test_main_materialized_registries_have_no_duplicate_or_missing_ids` / `test_AC8_13_17_ac_traceability_runs_registry_generation_check` | `tests/tooling/test_generate_ac_registry.py` / `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.18 | Brokerage portfolio gate validates market valuation adjustment lines even when unrelated asset lines lower total assets | `test_portfolio_valuation_gate_ignores_unrelated_negative_asset_lines` / `test_portfolio_market_adjustment_survives_unrelated_negative_asset_lines` | `tests/e2e/test_brokerage_upload_to_portfolio_value.py` / `apps/backend/tests/reporting/test_reporting_net_worth_components.py` | P0 |
| AC8.13.19 | Brokerage portfolio gate failures include holdings, valuation adjustment, non-portfolio asset, and balance-sheet diagnostics | `test_portfolio_valuation_gate_failure_diagnostics_are_actionable` | `tests/e2e/test_brokerage_upload_to_portfolio_value.py` | P0 |
| AC8.13.20 | CI change classification is covered by multi-commit and markdown edge-case regression tests | `test_AC8_13_20_*` | `tests/tooling/test_ci_change_classifier.py` | P1 |
| AC8.13.21 | Provider-backed staging AI/OCR gate runs inside a manual staging dispatch (inheriting `workflow_dispatch`) and via the on-demand `deploy.yml`, never auto-after-CI | `test_AC8_13_21_staging_ai_ocr_gate_runs_under_manual_dispatch` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.22 | Staging deploys an explicitly supplied published release `version_ref` (`vX.Y.Z` tag) on `workflow_dispatch`; it does not build or promote images inside the deploy workflow | `test_AC8_13_22_staging_deploys_manually_dispatched_version_ref`, `test_AC8_13_22_release_coordinate_rejects_non_release_ref`, `test_AC8_13_22_release_coordinate_rejects_whitespace_version_ref`, `test_AC8_13_22_release_coordinate_fetches_only_requested_tag` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.23 | Automatic staging deploy health and AI/OCR validation run in one serialized post-merge workflow unit | `test_AC8_13_23_post_merge_deploy_and_ai_ocr_are_one_serial_unit` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.24 | AC traceability audit is uploaded as a CI artifact instead of failing on a stale committed report | `test_AC8_13_24_ac_traceability_uploads_audit_artifact_without_stale_doc_gate` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.25 | Full CI starts deterministic test and image jobs after change classification while `finish` aggregates lint, AC traceability, tests, image validation, coverage, and skipped-job semantics | `test_AC8_13_25_full_ci_aggregates_static_traceability_and_test_gates` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.26 | CI metrics contract fails when source roots, coverage policy, workflow gates, or AC traceability semantics drift | `test_AC8_13_26_*` | `tests/tooling/` | P0 |
| AC8.13.27 | Pull requests do not publish Coveralls status contexts; main-only Coveralls reporting remains separate from local deterministic coverage gates | `test_AC8_13_27_*` | `tests/tooling/` | P0 |
| AC8.13.28 | Deterministic upload-to-dashboard gate runs as a critical fresh-user staging E2E | `test_statement_upload_to_dashboard_vision_hard_gate`, `test_AC8_13_28_vision_hard_gate_uses_statement_id_link_locator`, `test_AC8_13_28_vision_hard_gate_waits_for_review_payload_before_approval` | `tests/e2e/test_vision_upload_to_dashboard_hard_gate.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.29 | Stage 1 review auto-posts journal entries from the deterministic fixture | `test_statement_upload_to_dashboard_vision_hard_gate` | `tests/e2e/test_vision_upload_to_dashboard_hard_gate.py` | P0 |
| AC8.13.30 | Reconciliation rerun is idempotent and Stage 2 run review reaches a cleared completion state | `test_statement_upload_to_dashboard_vision_hard_gate`, `test_AC8_13_30_vision_hard_gate_waits_for_stage2_queue_page_payload` | `tests/e2e/test_vision_upload_to_dashboard_hard_gate.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.31 | Processing Account summary and pending page stay visible and correct for the cleared run | `test_statement_upload_to_dashboard_vision_hard_gate` | `tests/e2e/test_vision_upload_to_dashboard_hard_gate.py` | P0 |
| AC8.13.32 | Dashboard, balance sheet, income statement, and cash-flow totals exactly match the deterministic upload fixture | `test_statement_upload_to_dashboard_vision_hard_gate` | `tests/e2e/test_vision_upload_to_dashboard_hard_gate.py` | P0 |
| AC8.13.33 | Shared E2E setup caches Python virtualenv and Playwright browser artifacts for staging and preview gates and exports repository-root `PYTHONPATH` for stable `tests.e2e.*` imports | `test_AC8_13_33_e2e_setup_caches_virtualenv_and_playwright_browsers` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.34 | CI and post-merge workflows append queue, execution, and per-job timing summaries to GitHub Step Summary | `test_AC8_13_34_*` | `tests/tooling/` | P1 |
| AC8.13.35 | AC traceability reporting distinguishes real test references from `_ac_stubs` and trivial placeholder assertions | `test_classifies_placeholder_assertion`, `test_classifies_pure_pass_ac_file_as_placeholder`, `test_classifies_ac_stub_directory`, `test_placeholder_and_stub_refs_do_not_count_as_real_coverage` | `tests/tooling/test_check_ac_traceability.py` | P0 |
| AC8.13.36 | Main CI builds SHA-tagged images, `deploy.yml` promotes those digests to an immutable `vX.Y.Z` release tag, and staging deploy consumes that tag without rebuilding or moving a `staging` tag | `test_AC8_13_36_post_merge_reuses_sha_tagged_staging_images` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.37 | AC traceability fails mandatory ACs that are covered only by `_ac_stubs` | `test_returns_one_with_stub_only` | `tests/tooling/test_check_ac_traceability.py` | P0 |
| AC8.13.38 | The app performs no Dokploy preview reclaim — on PR close it dispatches a vendor-neutral teardown to infra2 (which owns the 1:1 reclaim); the app keeps no cleanup/reconcile entrypoints, no host-hygiene commands, and emits no raw Dokploy responses | `test_AC8_13_38_*` | `tests/tooling/test_cleanup_pr_preview_resources.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.39 | Runtime and container versions stay aligned across local, CI, and Docker environments | `test_AC8_13_39_*` | `tests/tooling/test_toolchain_contract.py` | P0 |
| AC8.13.40 | PR CI dry-runs staging image builds before merge; main push CI is the only path that pushes SHA-tagged images | `test_AC8_13_40_pr_ci_dry_runs_staging_image_builds_before_merge` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.41 | Critical proof matrix fails when a core product proof path is backed only by broad or reference-only AC strings | `test_*critical_proof_matrix*` | `tests/tooling/test_check_critical_proof_matrix.py` | P0 |
| AC8.13.42 | Four-asset as-of net worth golden path runs as a critical fresh-user post-merge E2E | `test_four_asset_as_of_net_worth_golden_path`, `test_AC8_13_42_four_asset_net_worth_golden_path_is_post_merge_critical` | `tests/e2e/test_four_asset_net_worth_golden_path.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.44 | Local bootstrap provides one command for runtimes, dependency setup, pre-commit hooks, and container-runtime diagnostics | `test_AC8_13_44_*` | `tests/tooling/test_bootstrap_local.py`, `tests/tooling/test_cli_and_dev_servers.py`, `tests/tooling/test_toolchain_contract.py` | P0 |
| AC8.13.45 | Local verification entry points fail on the same backend format errors and route `make test` through the root Moon test command without hashing the infra submodule gitlink as a file input | `test_AC8_13_45_*` | `tests/tooling/test_cli_and_dev_servers.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.46 | PR preview non-LLM E2E uses strict gates and parallelism while narrowing execution to runtime/API/UI preview-relevant paths instead of the staging regression set | `test_AC8_13_46_pr_preview_non_llm_gate_matches_staging_strict_parallelism` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.47 | Remaining delivery-engine optimizations are captured in a tracked project recommendation note | `test_AC8_13_47_delivery_engine_recommendations_are_tracked` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.48 | Frontend gap tests cover route, component, and API helper paths so frontend LCOV line coverage reaches 99% | `test_AC8_13_48_*` | `apps/frontend/src/__tests__/stage2ReviewQueueCoverage99.test.tsx`, `apps/frontend/src/__tests__/statementReviewPage.coverage.test.tsx`, `apps/frontend/src/__tests__/statementDetailPage.coverage.test.tsx`, `apps/frontend/src/__tests__/StatementUploader.test.tsx`, `apps/frontend/src/__tests__/journalPage.test.tsx`, `apps/frontend/src/__tests__/reconciliationWorkbenchComponent.test.tsx`, `apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx`, `apps/frontend/src/__tests__/apiFunctions.test.ts`, `apps/frontend/src/__tests__/accountsPage.test.tsx`, `apps/frontend/src/__tests__/assetsPage.test.tsx`, `apps/frontend/src/__tests__/statementsPage.test.tsx`, `apps/frontend/src/__tests__/useWorkspaceHook.test.tsx`, `apps/frontend/src/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx`, `apps/frontend/src/__tests__/uiGapAudit.netWorthTimeSeries.test.tsx`, `apps/frontend/src/__tests__/uiGapAudit.processingVisibility.test.tsx` | P0 |
| AC8.13.49 | Staging AI/OCR gates publish audit input inventory and replay summary fields | `test_AC8_13_49_staging_ai_ocr_gate_publishes_audit_inventory_and_summary` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.50 | Critical proof matrix validates the closed macro outcome set from README through owner EPICs and E2E proof anchors | `test_AC8_13_50_*` | `tests/tooling/test_check_critical_proof_matrix.py` | P0 |
| AC8.13.51 | Staging deploy is manual (`workflow_dispatch`) only with a required deploy_v2-aligned `version_ref` input; it does not auto-follow main CI and does not poll for CI in-job | `test_AC8_13_51_staging_deploy_is_manual_dispatch_only` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.52 | Production release dry-run validates release prerequisites and image builds through shared release evidence/image digest tools without production mutation | `test_AC8_13_52_production_release_dry_run_does_not_mutate_production`, `test_AC8_13_52_production_release_checks_use_pinned_python`, `test_AC8_13_52_production_release_matches_exact_staging_run_name`, `test_AC8_13_52_release_evidence_tool_requires_exact_successful_staging_run`, `test_AC8_13_52_release_evidence_tool_reports_source_and_release_runs`, `test_AC8_13_52_release_evidence_tool_fails_without_staging_jobs`, `test_AC8_13_52_release_image_tool_reports_backend_and_frontend_digests`, `test_AC8_13_52_release_image_tool_fails_when_a_digest_is_missing` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.53 | Common owns SSOT, config and CI contracts, coverage policy, and isolation helpers; command entry points and tool-owned implementations live in `tools/`; PR CI avoids optional Moon bootstrap for heavy gates that run direct `pytest` or `npm` commands, with Moon availability covered as static config contracts | `test_AC8_13_53_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_ci_metrics_contract.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.54 | Critical proof matrix fails when README macro outcomes, matrix outcomes, or owner EPIC reverse declarations drift | `test_AC8_13_54_*` | `tests/tooling/test_check_critical_proof_matrix.py` | P0 |
| AC8.13.55 | Post-merge staging deploys only for runtime, deploy, E2E, staging workflow, toolchain, or infra-submodule changes | `test_AC8_13_55_*` | `tests/tooling/test_ci_change_classifier.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.56 | Coverage command entry points run from `tools/`; the shared policy stays in `common/coverage/policy.py`, and command implementations live under `tools/_lib/coverage/` | `test_AC8_13_56_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_ci_metrics_contract.py`, `tests/tooling/test_coverage_policy.py`, `tests/tooling/test_build_unified_lcov.py` | P0 |
| AC8.13.57 | SSOT and AC command entry points run from `tools/` while shared implementations live in the packages that own them (`common/testing/`, `common/meta/extension/`), with only the no-clean-fit generators still under `common/ssot/` | `test_AC8_13_57_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_ci_metrics_contract.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.58 | CI and toolchain command entry points run from `tools/`; reusable contracts live in the packages that own them (`common/runtime/`, `common/testing/`, `common/meta/extension/`), while report and shell command implementations live under `tools/_lib/` | `test_AC8_13_58_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_toolchain_contract.py`, `tests/tooling/test_ci_change_classifier.py`, `tests/tooling/test_github_workflow_timing_summary.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.59 | Config validation command entry points run from `tools/` while shared implementations live under `common/config/` | `test_AC8_13_59_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_check_env_keys.py`, `tests/tooling/test_validate_schemas.py` | P0 |
| AC8.13.60 | Deploy workflows do not keep no-op dependency checks or warning-only performance probes that cannot block release risk | `test_AC8_13_60_deploy_workflows_have_no_nonblocking_noop_gates` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.61 | Visual regression residual is explicitly owned by EPIC-008 as a P3 future testing capability | `test_AC8_13_61_visual_regression_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P3 |
| AC8.13.62 | Test observability residuals are explicitly owned by EPIC-008 with current replacements and future dashboard/notification/trend scope | `test_AC8_13_62_test_observability_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P2 |
| AC8.13.63 | Performance testing residual is explicitly owned by EPIC-008 with current Locust/staging coverage and future P95 trend gate scope | `test_AC8_13_63_performance_testing_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P2 |
| AC8.13.64 | Production release verifies DB, S3, app vendor-neutral OTEL readiness, API, and frontend before completing deploy (proving the observability backend ingests is infra2's job) | `test_AC8_13_64_*` | `tests/tooling/test_production_infra_smoke.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.65 | Production release reuses successful main CI proof instead of rerunning container-backed tests in the release lane | `test_AC8_13_52_production_release_dry_run_does_not_mutate_production`, `test_AC8_13_9_production_release_runs_prod_safe_e2e_smoke` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.66 | Coveralls uploads strip branch counters so external percentages track the line-only unified coverage gate | `test_AC8_13_66_*` | `tests/tooling/test_build_unified_lcov.py`, `tests/tooling/test_strip_lcov_branches.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.67 | Production release preserves deployed version metadata from image build through Dokploy runtime health | `test_AC8_13_67_production_release_preserves_version_metadata` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.68 | E2E EPIC traceability fails E2E-root test functions missing function-level EPIC IDs or project EPICs without E2E owners | `test_AC8_13_68_*` | `tests/tooling/test_check_e2e_epic_traceability.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.69 | Local test lifecycle binds namespaced infra to ephemeral host ports so parallel branches do not collide | `test_namespaced_infra_uses_ephemeral_host_ports` | `apps/backend/tests/unit/infra/test_test_lifecycle.py` | P0 |
| AC8.13.70 | E2E EPIC traceability fails README EPIC map drift and unclassified E2E-like assets outside declared roots | `test_AC8_13_70_*` | `tests/tooling/test_check_e2e_epic_traceability.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.71 | One lifecycle tool stands PR previews UP (deploy) and writes stable preview metadata; on PR close the workflow dispatches a `preview-teardown` signal to infra2 — the app owns no Dokploy reclaim (cleanup/reconcile/delete) | `test_AC8_13_71_*` | `tests/tooling/test_pr_preview_lifecycle.py` | P0 |
| AC8.13.72 | Dokploy deploy diagnostics redact raw responses, log only allowlisted effective environment/config details, parse deployment records as typed object records, fail before readiness when fixed deploy_v2 sees rollout error/no terminal new record, and retain redacted rollout diagnostics for legacy preview compatibility | `test_AC8_13_72_*` | `tests/tooling/test_dokploy_redaction.py`, `tests/tooling/test_pr_preview_lifecycle.py` | P0 |
| AC8.13.73 | The app owns no VPS host hygiene — generic host GC (Docker/journald/disk prune) is infra2-owned (`tools/host_hygiene_schedule.py` + the ops-checks re-ensure job); the app ships no `vps_host_hygiene` module and provisions no Dokploy host-schedule | `test_AC8_13_73_*` | `tests/tooling/test_cleanup_pr_preview_resources.py` | P0 |
| AC8.13.74 | The app's scheduled maintenance performs no Dokploy preview reconcile and no host hygiene — it only prunes the app's own stale GHCR PR image tags (Dokploy preview reclaim is infra2-owned) | `test_AC8_13_74_*` | `tests/tooling/test_cleanup_pr_preview_resources.py` | P0 |
| AC8.13.75 | Reporting-only coverage gate summary cannot fail the final CI aggregation job if GitHub Step Summary writes fail | `test_AC8_13_75_coverage_gate_summary_is_nonblocking` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.76 | Playwright mobile UX coverage proves Stage 1 and Stage 2 review workflows avoid document-level horizontal scroll and expose direct completion actions at phone widths | `AC16.26.*` | `apps/frontend/playwright/mobile-ux.spec.ts` | P0 |
| AC8.13.77 | Registry-to-EPIC consistency fails active stub or orphan AC entries instead of silently excluding them | `test_AC8_13_77_*` | `tests/tooling/test_lint_doc_consistency.py` | P0 |
| AC8.13.78 | Mandatory AC traceability requires at least one real proof file that is mapped to a CI-required execution stage | `test_AC8_13_78_*` | `tests/tooling/test_check_ac_traceability.py` | P0 |
| AC8.13.79 | Local E2E command routing distinguishes root deployment E2E from backend Tier-1 API E2E | `test_AC8_13_79_*` | `tests/tooling/test_cli_and_dev_servers.py` | P0 |
| AC8.13.80 | AC coverage analysis supports no-write and stale-report check modes for local verification | `test_AC8_13_80_*` | `tests/tooling/test_analyze_test_ac_coverage.py` | P0 |
| AC8.13.81 | Coverage threshold documentation links to code-owned thresholds instead of copying mutable numeric values | `test_AC8_13_81_*` | `tests/tooling/test_lint_doc_consistency.py` | P1 |
| AC8.13.82 | Playwright responsive UX coverage proves account and review layouts avoid mobile document overflow and desktop local table clipping | `AC2.17.1`, `AC16.27.2`, `AC16.27.3` | `apps/frontend/playwright/mobile-ux.spec.ts` | P0 |
| AC8.13.83 | Personal report package representative fixture contract defines bank cash, income/expense activity, brokerage holdings, manual property valuation, liability, restricted compensation, notes, traceability anchors, and exact Decimal expected outputs | `test_AC8_13_83_representative_package_fixture_contract_defines_exact_outputs` | `tests/tooling/test_personal_report_package_fixture_contract.py` | P0 |
| AC8.13.84 | Personal report package post-merge E2E consumes the representative fixture contract instead of duplicating financial constants or expected totals inline | `test_AC8_13_84_personal_package_e2e_consumes_representative_fixture_contract` | `tests/tooling/test_personal_report_package_fixture_contract.py` | P0 |
| AC8.13.85 | Personal financial report package macro proof is promoted to covered only when the representative fixture contract ACs are part of the critical proof matrix | `test_AC8_13_85_personal_package_macro_proof_is_promoted_after_fixture_contract` | `tests/tooling/test_personal_report_package_fixture_contract.py` | P0 |
| AC8.13.86 | CI fast feedback jobs start after change classification without waiting for behavior-only backend gates | `test_AC8_13_86_*` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.87 | Personal report package fixture contract pins brokerage, dividend, and market-price expected outputs as Decimal-safe audit fixtures | `test_AC8_13_87_personal_package_fixture_pins_brokerage_dividend_and_market_price_outputs` | `tests/tooling/test_personal_report_package_fixture_contract.py` | P0 |
| AC8.13.88 | Personal report package post-merge E2E consumes the audit-grade brokerage, dividend, market-price, and traceability identifier expected outputs | `test_AC8_13_88_personal_package_e2e_consumes_audit_grade_expected_outputs` | `tests/tooling/test_personal_report_package_fixture_contract.py` | P0 |
| AC8.13.89 | The runner-local full-stack smoke/E2E gate runs synchronously on `pull_request` (the merge authority, a real required check, not async via `workflow_run`); the on-demand persistent Dokploy preview is built from the PR source on the host without pushing, preflighting, pulling, or deleting PR preview images | `test_AC8_13_89_pr_preview_follows_ci_without_pr_image_builds` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.90 | Frontend exposes `/frontend-version.json` with deployed `git_sha`/`version` metadata for PR preview readiness checks | `AC8.13.90 returns deployed frontend version metadata for PR preview readiness` | `frontendVersionRoute.test.ts` | P0 |
| AC8.13.92 | Frontend Vitest coverage keeps a code-owned 98% baseline for line, statement, and function metrics plus an explicit branch floor while representative low-coverage routes and workflow surfaces stay covered | `AC8.13.92*` | `apps/frontend/src/__tests__/coverageBaseline.test.ts`, `apps/frontend/src/__tests__/personalReportPackagePage.test.tsx`, `apps/frontend/src/__tests__/workflowSurfaces.test.tsx`, `apps/frontend/src/__tests__/chatPanelComponent.test.tsx`, `apps/frontend/src/__tests__/investmentPerformanceSchedule.test.tsx`, `apps/frontend/src/__tests__/journalPage.test.tsx`, `apps/frontend/src/__tests__/sankeyChartComponent.test.tsx`, `apps/frontend/src/__tests__/toastProviderComponent.test.tsx`, `apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx` | P0 |
| AC8.13.93 | Staging is mutated only by an explicit manual `workflow_dispatch` with a required release `version_ref` input; no auto path can promote images or change Dokploy, and structured deploy failure context is preserved | `test_AC8_13_93_staging_promotion_requires_manual_dispatch` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.94 | CI/CD documentation separates environment taxonomy from pipeline stages and declares the sparse env x stage execution matrix | `test_AC8_13_94_env_and_pipeline_stage_contract_is_documented` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.95 | Local verification guidance defaults to affected fast tests and defines risk-triggered escalation for high-impact paths | `test_AC8_13_95_local_fast_gate_and_escalation_policy_are_documented` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.96 | PR preview relevance classification includes preview workflow, lifecycle, and config changes while excluding docs-only and app test-only changes | `test_AC8_13_96_pr_preview_classifier_includes_preview_infrastructure_paths` | `tests/tooling/test_ci_change_classifier.py` | P0 |
| AC8.13.97 | CI change classification exposes table-driven env/stage rules so shared runtime paths cannot drift between PR preview and staging deployed proof | `test_AC8_13_97_*` | `tests/tooling/test_ci_change_classifier.py` | P0 |
| AC8.13.98 | Legacy Dokploy preview composes preserve compose identity, update allowlisted deploy env, and re-run Dokploy `compose.redeploy` without a pre-stop or separate `compose.start` call so historical cleanup/reconciliation compatibility can still reason about stuck previews safely | `test_AC8_13_98_existing_preview_compose_is_redeployed_without_pre_stop` | `tests/tooling/test_pr_preview_lifecycle.py` | P0 |
| AC8.13.99 | Frontend local and CI gates run full TypeScript checking, including tests, instead of relying only on Next production build type checks | `test_AC8_13_99_frontend_typecheck_is_a_required_gate` | `tests/tooling/test_frontend_typecheck_contract.py` | P0 |
| AC8.13.100 | Runner preview readiness is bounded and observable before smoke/E2E; legacy Dokploy route diagnostics remain as compatibility evidence for historical preview cleanup/reconciliation tooling | `test_AC8_13_100_pr_preview_runner_readiness_is_bounded_and_observable`, `test_AC8_13_100_infra2_route_canary_is_available` | `tests/tooling/test_pr_preview_lifecycle.py` | P0 |
| AC8.13.101 | PR preview E2E consumes the runner-local `http://localhost:8080` URL as the merge-authority gate; after it passes, a non-blocking persistent Dokploy preview is deployed at `report-pr-<N>.<domain>` and released via `compose.delete` on PR close; lifecycle helpers preserve stable/commit preview URL derivation | `test_AC8_13_101_preview_app_url_prefers_stable_alias`, `test_AC8_13_101_pr_test_workflow_uses_runner_preview_url` | `tests/tooling/test_pr_preview_lifecycle.py` | P0 |
| AC8.13.102 | The PR-preview deploy helpers keep bounded rollout diagnostics, redaction, transient retry handling, and stuck-compose recovery semantics so a preview deploy fails safe even though current default PR preview no longer creates PR images | `test_AC8_13_102_preview_network_is_pr_scoped_to_limit_subnet_usage`, `test_AC8_13_102_dokploy_deploy_waits_for_worker_done_status`, `test_AC8_13_102_dokploy_rollout_record_window_allows_worker_queue`, `test_AC8_13_102_late_rollout_record_gets_completion_window`, `test_AC8_13_102_dokploy_rollout_timeout_fails_before_readiness`, `test_AC8_13_102_dokploy_rollout_error_fails_before_readiness`, `test_AC8_13_102_done_compose_without_new_record_fails_before_readiness`, `test_AC8_13_102_rollout_poll_retries_transient_dokploy_api_failure`, `test_AC8_13_102_compose_error_logs_redacted_deployment_diagnostics`, `test_AC8_13_102_stale_compose_error_waits_for_new_rollout`, `test_AC8_13_102_preview_source_disables_dokploy_auto_deploy`, `test_AC8_13_102_new_preview_redeploys_when_initial_deploy_record_is_missing`, `test_AC8_13_102_existing_preview_without_deployments_is_recreated`, `test_AC8_13_102_existing_preview_rollout_tracks_new_deployment_ids`, `test_AC8_13_102_existing_preview_missing_deploy_record_recreates_once`, `test_AC8_13_102_recreated_preview_missing_record_fails_before_readiness`, `test_AC8_13_102_existing_preview_rollout_error_recreates_once`, `test_AC8_13_102_new_preview_missing_after_redeploy_recreates_once`, `test_AC8_13_102_new_preview_rollout_error_still_fails`, `test_AC8_13_102_api_call_retries_transient_failures_on_get`, `test_AC8_13_102_dokploy_api_call_invalid_retry_delay_fallback`, `test_AC8_13_102_dokploy_api_call_non_transient_curl_error_does_not_retry` | `tests/tooling/test_pr_preview_lifecycle.py` | P0 |
| AC8.13.103 | Main post-merge staging publishes one commit-level `Post-merge Delivery` check that fails release-critical staging build/deploy and provider connectivity failures, while recording right-shifted full AI/OCR regression evidence without blocking production eligibility | `test_AC8_13_103_post_merge_delivery_summary_check_aggregates_staging_gates` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.104 | Automatic staging AI/OCR runs only for provider, extraction, statement parsing, PDF fixture, AI/OCR workflow, or critical LLM proof path changes; normal runtime deploys keep staging smoke/E2E but skip provider spend | `test_AC8_13_104_staging_ai_ocr_runs_only_for_provider_risk_paths` | `tests/tooling/test_ci_change_classifier.py` | P0 |
| AC8.13.105 | Post-merge staging keeps FIFO ordering but collapses train wait, staging classification, and deploy into one runner job to avoid a second GitHub Actions scheduling gap before staging mutation | `test_AC8_13_13_staging_deploy_fast_fail_guardrails`, `test_AC8_13_55_post_merge_staging_is_scoped_to_deploy_relevant_paths` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.107 | PR preview uploads runner preview context artifacts without PR image preflight, while legacy lifecycle deploy helpers still redact context for compatibility tests | `test_AC8_13_107_deploy_action_fails_fast_on_missing_required_inputs`, `test_AC8_13_107_preview_deploy_context_is_written_without_secrets`, `test_AC8_13_107_pr_preview_workflow_uploads_context_without_image_preflight` | `tests/tooling/test_pr_preview_lifecycle.py` | P0 |
| AC8.13.108 | Main post-merge staging deploy failures publish structured failure domain, failed step, and failure summary in the deploy context artifact and Post-merge Delivery summary so deploy_v2 dependency setup, Dokploy rollout, route health, E2E setup, and application E2E failures can be separated without manual log scraping | `test_AC8_13_93_staging_promotion_requires_manual_dispatch`, `test_AC8_13_103_post_merge_delivery_summary_check_aggregates_staging_gates`, `test_AC8_13_108_staging_failure_context_fails_closed_on_classifier_and_unknown_failures` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.109 | Post-merge staging AI/OCR gate tests use isolated users, browser-cookie auth, deterministic UI waits, and cleanup-capable test accounts; PR tooling rejects shared mutable users, localStorage bearer tokens, and generic deployed-env idle waits before provider-backed replay | `test_AC8_13_109_ai_ocr_gate_tests_use_isolated_users`; `test_AC8_13_109_ai_ocr_gate_tests_use_cookie_auth_for_api_calls`; `test_AC8_13_109_ai_ocr_gate_tests_avoid_networkidle_waits`; `test_delete_current_user_removes_authenticated_user`; `test_delete_user_does_not_allow_cross_user_deletion` | `tests/tooling/test_staging_ai_ocr_gate_contract.py`; `apps/backend/tests/api/test_users_router.py` | P0 |
| AC8.13.110 | CI change classification emits structured Env x Stage JSON outputs and matrix summaries as the sole machine-readable gate contract; the per-env legacy scalar outputs (`pr_preview_required`, `staging_required`, `staging_ai_ocr_required`) are retired now that every workflow consumer derives its own scalar from the structured matrix | `test_AC8_13_110_*` | `tests/tooling/test_ci_change_classifier.py` | P0 |
| AC8.13.111 | CI change classification structured Env x Stage outputs cover the complete environment axis (`local`, `pr`, `pr-preview`, `staging`, `prd`) while keeping PR heavy gating and deployed-environment gates represented as matrix cells | `test_AC8_13_111_*` | `tests/tooling/test_ci_change_classifier.py` | P0 |
| AC8.13.112 | Delivery-engine recommendations, SSOT, workflow gates, and contract tests stay aligned around structured Env x Stage consumers as the sole gate contract; the per-env legacy scalar classifier outputs are retired and the simplification path is recorded as complete | `test_AC8_13_112_sparse_matrix_recommendation_tracks_simplification_path`, `test_AC8_13_112_workflows_consume_structured_env_stage_gates` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.113 | Sparse Env x Stage reviews record the three newest successful and three newest failed evidence samples for active delivery lanes, then summarize delivery-speed balance, end-to-end consistency, quality fallback, resource leak candidates, and the safe simplification boundary | `test_AC8_13_113_sparse_matrix_evidence_and_resource_leak_audit_are_recorded` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.114 | The in-runner E2E gate runs synchronously on `pull_request` as a real required check a fast/auto merge cannot bypass (not async via `workflow_run`, which a merge could outrun); PR close triggers cleanup, not a gate | `test_AC8_13_114_pr_preview_follows_successful_ci_workflow_run` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.115 | Runner preview readiness is bounded before smoke/E2E starts, with stack logs emitted on failure | `test_AC8_13_115_readiness_fail_fast` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.116 | Post-merge → staging start latency is reduced by removing redundant heavy re-run on push to main | `test_AC8_13_116_skip_heavy_ci_on_main_push` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.118 | Critical-path timeouts and retries are documented in `docs/ssot/ci-cd.md` | `test_AC8_13_118_timeouts_and_retries_documented` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.119 | One delivery hardening PR contracts the known leak paths: PR preview leftovers, legacy GHCR PR tag accumulation, stale staging or production routes, provider-backed external-state residue, and Docker build cache and stopped containers, while preserving the sparse Env x Stage speed boundary | `test_AC8_13_119_delivery_resource_leak_hardening_is_contracted` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.120 | Provider-risk staging changes run one dedicated real AI provider connectivity smoke after deployed health and non-LLM E2E; transient provider 5xx/timeouts degrade delivery without failing main, while provider 4xx stays a hard gate | `test_AC8_13_120_staging_runs_lightweight_provider_connectivity_smoke`; `test_staging_ai_provider_chat_connectivity` | `tests/tooling/test_post_merge_e2e_gates.py`; `tests/e2e/test_ai_provider_connectivity.py` | P0 |
| AC8.13.121 | PR CI runs a schema migration contract against ephemeral Postgres with `alembic upgrade head`, `alembic check`, uploaded context, and `finish` aggregation | `test_AC8_13_121_pr_ci_runs_schema_migration_contract` | `tests/tooling/test_schema_quality_contract.py` | P0 |
| AC8.13.122 | Backend schema drift guard no longer treats an out-of-date Alembic target or missing CLI as success; PR CI `schema-migrations` owns hard proof | `test_AC8_13_122_schema_drift_guard_does_not_accept_outdated_targets` | `tests/tooling/test_schema_quality_contract.py` | P0 |
| AC8.13.123 | Schema guardrails scan the real `apps/backend/migrations/versions` directory instead of a test-local path | `test_AC8_13_123_schema_guardrails_scan_real_migration_directory` | `tests/tooling/test_schema_quality_contract.py` | P0 |
| AC8.13.124 | AC traceability gate and uploaded audit builder consume the same SSOT test-surface definition, including frontend Playwright tests | `test_AC8_13_124_traceability_gate_and_audit_builder_share_test_surface` | `tests/tooling/test_schema_quality_contract.py` | P1 |
| AC8.13.125 | PR preview waits stay bounded: current runner preview has a hard workflow timeout and legacy Dokploy busy-queue extensions cannot exceed the compatibility rollout deadline | `test_AC8_13_125_busy_dokploy_queue_cannot_extend_past_rollout_deadline`; `test_AC8_13_125_pr_preview_runner_lifecycle_has_hard_timeout` | `tests/tooling/test_pr_preview_lifecycle.py` | P1 |
| AC8.13.126 | Runtime incident response SSOT centralizes service-failure triage and stability proof ownership, while deployment, observability, CI/CD, and environment smoke docs link to it instead of duplicating playbooks | `test_AC8_13_126_runtime_incident_response_ssot_centralizes_triage` | `tests/tooling/test_runtime_incident_response_ssot.py` | P0 |
| AC8.13.127 | Backend business persistence has a production-faithful Alembic-built proof lane that keeps user foreign keys intact while exercising a representative accounting write/read path | `test_AC8_13_127_alembic_business_persistence_keeps_user_fk_contract` | `apps/backend/tests/integration/test_production_faithful_business_persistence.py` | P0 |
| AC8.13.128 | Detached `user_id=uuid4()` owner shortcuts in DB-backed backend tests are counted and cannot grow without an explicit budget update | `test_AC8_13_128_*` | `tests/tooling/test_detached_owner_guard.py` | P0 |
| AC8.13.129 | Testing SSOT distinguishes fast `create_all()` fixtures, PR Alembic schema proof, and the production-faithful backend business persistence lane | `test_AC8_13_129_schema_docs_distinguish_fast_fixture_and_production_faithful_lane` | `tests/tooling/test_detached_owner_guard.py` | P0 |
| AC8.13.130 | The detached-owner guard counts only persisted (`db.add`/`db.add_all`) `user_id=uuid4()` rows — the real foreign-key risk — excluding transient in-memory and service-argument uses, collapsing the historically-inflated budget to the persisted rows | `test_AC8_13_130_counts_only_persisted_detached_owners` | `tests/tooling/test_detached_owner_guard.py` | P1 |
| AC8.13.131 | Bottom-up proof exceptions and code-owned surfaces are classified in `docs/ssot/governance-exceptions.yaml` with a typed `proof_exceptions`/`code_owned_surfaces` entry (id, owner, reason, issue), validated by `tools/check_governance_exceptions.py`, leaving the legacy SSOT governance `exceptions` list intact (#524) | `test_AC8_13_131_*` | `tests/tooling/test_governance_exceptions_registry.py` | P1 |
| AC8.13.132 | Every test/support file with no AC reference stays classified in `docs/project/traceability-exceptions.md`, with no unclassified drift and no product E2E test parked on the allow-list (#511) | `test_AC8_13_132_*` | `tests/tooling/test_no_ac_test_classification.py` | P1 |
| AC8.13.133 | Cross-document SSOT concepts (reconciliation thresholds, reconciliation/confirmation state machines, extraction confidence tiers, confidence-tier rollup) are registered in `docs/ssot/MANIFEST.yaml` with anchored owners backed by explicit `<a id>` anchors (#340) | `test_AC8_13_133_*` | `tests/tooling/test_ssot_cross_document_anchors.py` | P1 |
| AC8.13.134 | Consolidated/archived stale docs stay absent and every mkdocs `nav` markdown target resolves (no dangling internal links after the consolidation) (#350) | `test_AC8_13_134_*` | `tests/tooling/test_stale_docs_consolidation.py` | P1 |
| AC8.13.135 | The AC-index gate's PROTECTION dashboard reports mandatory-AC coverage as per-type counts (`has_real_ref` / `has_proof` / `has_score` / `has_mirror`), never conflating L1 reference presence with behavioral proof, so a passing gate cannot be read as misleading behavioral assurance (re-anchored from the retired standalone traceability report) | `test_AC8_13_135_protection_dashboard_separates_reference_from_behavioral` | `tests/tooling/test_ac_index_consistency.py` | P0 |
| AC8.13.136 | A content-level secret scan (gitleaks) runs in both the pre-commit hooks and the CI `lint` job (local==CI parity), blocking credential material by content rather than by filename so `.gitignore` is not the only line of defense | `test_AC8_13_136_gitleaks_runs_in_precommit_and_ci` | `tests/tooling/test_secret_scan_gate.py` | P0 |
| AC8.13.137 | The staging AI/OCR gate summarizes its JUnit output into real pass/fail counts and names the failing corpus docs (instead of a binary "Failures observed: 1+" with verified counts "unknown"), so a red gate is diagnosable ([#1089](https://github.com/wangzitian0/finance_report/issues/1089)) | `test_AC8_13_137_summarize_junit_reports_per_doc_failures`; `test_AC8_13_137_render_junit_summary_lists_failed_tests`; `test_AC8_13_137_summarize_junit_tolerates_missing_xml` | `tests/tooling/test_staging_ai_ocr_gate_contract.py` | P1 |
| AC8.13.138 | The AC-score ratchet baseline is a PERSISTED ratchet stored conflict-free as sorted, one-AC-per-line JSONL with a `merge=union` gitattribute, loading into the same in-memory shape the ratchet uses — and the ratchet still fails on regression, missing evidence, or non-pass code (the derived aggregate views it once sat beside are now covered by AC8.13.139) | `test_AC8_13_138_baseline_is_sorted_jsonl_with_union_merge`, `test_AC8_13_138_baseline_loads_to_legacy_shape`, `test_AC8_13_138_ratchet_still_fails_on_regression_and_missing_ac` | `tests/tooling/test_proof_index_architecture.py` | P1 |
| AC8.13.139 | The cross-cutting proof/vision/status indexes are unified onto ONE AC-keyed graph (`common/testing/ac_graph.py`) built from sharded sources (EPIC docs, `@ac_proof` decorators, `vision.md`, `critical-proof-outcomes.yaml`, the JSONL ratchet); the critical-proof matrix, vision-proof matrix, and README EPIC-status table are DERIVED on demand and never committed-materialized; and `tools/check_ac_index.py` is exactly TWO gates — **Gate A INTEGRITY** (`check_integrity`, hard: every AC is managed/enumerated with a protection record AND no dangling reference — every `@ac_proof` resolves to a real test + real AC, every vision item with an owner EPIC backs an AC, every macro outcome's proof_ids resolve, every mandatory active AC has a real test reference, with the per-edge-type messages preserved verbatim) and **Gate B PROTECTION RATCHET** (see AC8.13.140) — instead of N byte-compares | `test_AC8_13_139_gate_passes_on_consistent_tree`, `test_AC8_13_139_gate_fails_on_dangling_vision_item`, `test_AC8_13_139_gate_fails_on_proof_missing_test_or_ac`, `test_AC8_13_139_gate_fails_on_mandatory_ac_without_proof`, `test_AC8_13_139_gate_fails_on_macro_outcome_missing_proof`, `test_AC8_13_139_gate_fails_on_ratchet_regression`, `test_AC8_13_139_no_committed_materialized_index_files` | `tests/tooling/test_ac_index_consistency.py` | P1 |
| AC8.13.140 | Gate B (PROTECTION RATCHET) of `tools/check_ac_index.py` is monotonic, per-type and conflict-safe: an AC with an all-empty protection record is still "managed" (managed = present in the structure, not that it has any test); part 1 is the per-AC behavioural-score floor (`ac-score-baseline.jsonl`, `merge=union`, unchanged); part 2 is a per-type COUNT floor (`docs/ssot/protection-floor.json`) where the current count of mandatory active ACs at each type (`has_real_ref`, `has_proof`, `has_score`, `has_mirror`) must be `>=` the committed floor — adding protection only RAISES the current count and passes without editing the floor file, the default all-zero/missing floor is valid, and floors are raised only by the explicit `--update-floor` action so protection-adding PRs never touch the file | `test_AC8_13_140_every_ac_managed_with_empty_protection_passes`, `test_AC8_13_140_count_floor_default_empty_passes`, `test_AC8_13_140_count_floor_fails_when_type_drops_below_floor`, `test_AC8_13_140_count_floor_passes_when_protection_added`, `test_AC8_13_140_update_floor_raises_floors`, `test_AC8_13_140_load_floor_rejects_malformed_value`, `test_AC8_13_140_write_floor_creates_missing_parent` | `tests/tooling/test_ac_index_consistency.py` | P1 |
| AC8.13.141 | The AC-index gate is OPERATIONALLY exactly TWO CI gates: the former standalone CI-stage traceability contract (`common.testing.check_ac_traceability.run_traceability`: a mandatory active AC must resolve to a real test reference in a CI-REQUIRED execution stage per `docs/ssot/test-execution-matrix.yaml`, with the placeholder-only/stub-only/unexecuted-only/missing classifications) and critical-proof contract (`common.testing.check_critical_proof_matrix.validate_matrix_contract`: per-proof trust_mode/mirror/required_markers/scope/ci_tier + manual_gate evidence + macro-outcome shape contract) gate STEPS are RETIRED as separate CI steps; their logic is FOLDED into `check_ac_index`'s Gate A INTEGRITY (`check_repo_contracts`) by importing those modules as LIBRARIES (no reimplementation, verbatim messages), so every failure they caught still fails the single gate, the index gate runs ONCE (lint job, not duplicated in `ac-traceability`), and no CI job name / required status context is renamed | `test_AC8_13_141_green_tree_old_gates_and_consolidated_agree`, `test_AC8_13_141_unexecuted_only_is_caught`, `test_AC8_13_141_placeholder_only_is_caught`, `test_AC8_13_141_stub_only_is_caught`, `test_AC8_13_141_missing_is_caught`, `test_AC8_13_141_critical_proof_invalid_trust_mode_caught`, `test_AC8_13_141_critical_proof_llm_missing_mirror_caught`, `test_AC8_13_141_critical_proof_missing_marker_caught`, `test_AC8_13_141_critical_proof_manual_gate_without_evidence_caught`, `test_AC8_13_141_consolidated_gate_surfaces_critical_proof_errors`, `test_AC8_13_141_old_standalone_gate_steps_removed_from_ci`, `test_AC8_13_141_single_ac_index_gate_runs_exactly_once_per_required_path`, `test_AC8_13_141_ci_job_names_and_required_contexts_unchanged` | `tests/tooling/test_two_gate_consolidation.py` | P1 |
| AC8.13.142 | CI simplification keeps a transitional gate inventory where every workflow job has exactly one proof `stage` and one `task_category`; the inventory matches live workflow jobs and `finish.needs`, rejects legacy `category` keys, and records resolved duplicate cleanups so cleanup PRs do not leave both old and new entrances behind {tier:CODE-ONLY} {proof:property} | `test_AC8_13_142_ci_gate_inventory_uses_stage_and_task_category_per_job`, `test_AC8_13_142_finish_inventory_matches_ci_fan_in`, `test_AC8_13_142_duplicate_cleanup_is_explicit_not_implicit` | `tests/tooling/test_ci_gate_inventory.py` | P1 |
| AC8.13.143 | Main CI automatically opens or updates a reviewed baseline PR when `unified-coverage.json` rises, while PR CI keeps the committed no-regression gate and no new required status context is introduced | `test_AC8_13_143_unified_coverage_updates_baseline_through_pr_not_direct_main_push` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.144 | Production release rolls back through deploy_v2 to the pre-deploy production version and confirms health when a post-deploy route, infrastructure, smoke, or read-only E2E gate fails after mutation | `test_AC8_13_144_production_release_rolls_back_with_deploy_v2_after_post_deploy_failure` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.145 | Backend Tier-1 API E2E keeps PR fail-fast for speed but push/main runs the full Tier-1 suite so the JUnit artifact reports every failing API journey in one run | `test_AC8_13_145_backend_tier1_pr_fail_fast_but_main_reports_all_failures` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.146 | The report-branch-main auto preview dispatch runs only after successful main CI publishes SHA images, skips stale workflow_run completions, and infra2 deploy_v2 refuses to deploy branch-form `main` unless it resolves to the exact payload SHA | `test_AC8_13_146_report_main_dispatch_waits_for_ci_images` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.147 | Frontend PR CI is split into build/typecheck, Vitest coverage, provider-free Playwright, and telemetry E2E jobs while preserving `coverage-frontend`, frontend Vitest JUnit evidence, `unified-coverage` fan-in, AC behavioral ratchet fan-in, and `finish` aggregation over every frontend gate | `test_AC8_13_147_frontend_ci_split_preserves_merge_authority` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.148 | Backend fast-test CI shards rebalance the current critical path with a 5-way `pytest-split` matrix, a committed duration seed, least-duration assignment, and a seed-size guard so CI cannot silently fall back to unseeded even splitting | `test_AC8_13_148_backend_shards_use_seeded_5_way_split` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.149 | CI fan-in jobs trim post-backend tail work without weakening merge authority: unified coverage runs stdlib Python over scoped coverage artifacts, and the AC behavioral ratchet downloads only JUnit-producing test-context artifacts | `test_AC8_13_149_fan_in_jobs_download_only_required_artifacts` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.150 | AC is the only coverage key for CI proof placement: `@ac_proof` remains backward compatible while each proof edge can carry execution metadata as `proof(name, stage, task_category)`, where `stage` and `task_category` are proof attributes rather than identity keys and remain separate from authority tier / `proof_kind` {tier:CODE-ONLY} {proof:property} | `test_AC8_13_150_ac_proof_execution_model_is_ac_keyed_and_backward_compatible` | `tests/tooling/test_ac_proof_execution_model.py` | P1 |
| AC8.13.151 | CI gate inventory vocabulary is shared with the AC proof execution helper: top-level `stages` and `task_categories` match `common.testing.ac_proof_execution` exactly, so docs, runtime proof metadata, and inventory contracts cannot drift independently {tier:CODE-ONLY} {proof:property} | `test_AC8_13_151_ci_gate_inventory_uses_shared_proof_execution_vocabulary` | `tests/tooling/test_ci_gate_inventory.py` | P1 |
| AC8.13.152 | Workflow consumers keep Env x Stage as the classifier-owned source of truth: CI and PR preview jobs normalize structured classifier outputs into compatibility scalar outputs, downstream jobs consume only those normalized outputs, and no downstream job reimplements changed-path classification or ad hoc path logic {tier:CODE-ONLY} {proof:property} | `test_AC8_13_152_workflow_consumers_keep_classification_single_owned` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.153 | The staging AI/OCR corpus gate body lives once in a reusable `staging-ai-ocr-gate.yml` (`workflow_call`) consumed by both the inline staging deploy chain and the manual `staging-ai-ocr-gate` dispatch; the two entrances are `uses:` callers that differ only by a `blocking` input (record-only vs fail-fast) plus checkout/expected_sha, the duplicated job body is removed, and the cleanup is recorded in the gate inventory {tier:CODE-ONLY} {proof:property} | `test_AC8_13_153_staging_ai_ocr_gate_is_a_single_reusable_workflow` | `tests/tooling/test_ci_gate_inventory.py` | P1 |
| AC8.13.154 | The production release line (`dry-run`, `deploy`) is split out of `deploy.yml` into a manual-dispatch-only `release.yml` with a `production-release-<version_ref>` concurrency group (`cancel-in-progress: false`) so two prod releases never run concurrently; `deploy.yml` keeps staging deploy and tag-push promote, and the workflow contract plus gate inventory track the new file and re-homed job ids {tier:CODE-ONLY} {proof:property} | `test_AC8_13_154_production_release_line_lives_in_release_yml` | `tests/tooling/test_ci_gate_inventory.py` | P1 |
| AC8.13.155 | The former app-side reclaim split is retired: `preview.yml#cleanup` now dispatches a `preview-teardown` signal to infra2 (which owns the 1:1 reclaim via `preview-teardown.yml` + the hourly `preview-leak-check` fallback), and `maintenance.yml#cleanup` is GHCR-image-pruning only; the `pr_preview_cleanup_event_vs_scheduled` inventory entry records this `retired` state, not a `keep_separate` reclaim split {tier:CODE-ONLY} {proof:property} | `test_AC8_13_155_pr_preview_reclaim_is_dispatched_to_infra2` | `tests/tooling/test_ci_gate_inventory.py` | P1 |
| AC8.13.156 | The staging AI/OCR production-promotion blocking path runs only the minimal `AI/OCR Canary` corpus — one representative brokerage upload→parse→import→value liveness check (`tests/e2e/test_brokerage_upload_to_portfolio_value.py`) with no broad audit assertions (`report_verifications == 0`); the canary corpus is curated in `tools/staging_ai_ocr_gate_contract.py` (`canary_files()`) as a subset of the derived `llm` post-merge proofs and runs via the reusable gate's `corpus: canary` input {tier:CODE-ONLY} {proof:property} | `test_AC8_13_156_canary_corpus_is_minimal_liveness` | `tests/tooling/test_staging_ai_ocr_gate_contract.py` | P1 |
| AC8.13.157 | The heavy LLM audit journeys (full statement journey, four-asset net-worth golden path, personal financial report package) run as a separate `audit-replay.yml` job on `schedule:` (nightly) + `workflow_dispatch:` that calls the reusable gate with `corpus: audit_replay` and `blocking: false`, so the comprehensive corpus does NOT block production promotion by default {tier:CODE-ONLY} {proof:property} | `test_AC8_13_157_audit_replay_workflow_is_nightly_and_nonblocking` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.158 | The canary's provider transient-failure classification is owned by the `Staging Provider Gate`: the inline `ai-ocr-gate` canary only starts after `provider-gate` passes, where a `4xx`/config error blocks delivery (`config-failure`) while a `5xx`/timeout is a non-blocking `degraded` status {tier:CODE-ONLY} {proof:property} | `test_AC8_13_158_canary_transient_classification_owned_by_provider_gate` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.159 | Anti-regression: the blocking-path canary corpus and the audit-replay corpus are disjoint, every heavy audit journey is in the audit-replay corpus (never the canary), and the deploy-path `ai-ocr-gate` resolves `corpus: canary` so the heavy journeys cannot creep back into the blocking path {tier:CODE-ONLY} {proof:property} | `test_AC8_13_159_blocking_path_excludes_heavy_audit_journeys` | `tests/tooling/test_staging_ai_ocr_gate_contract.py` | P1 |
| AC8.13.160 | SSOT `docs/ssot/ci-cd.md` clearly distinguishes the blocking, minimal `AI/OCR Canary` from the nightly/manual, comprehensive `Audit Replay`, and records the canary-vs-audit split as a deliberate `keep_separate` decision in the gate inventory {tier:CODE-ONLY} {proof:property} | `test_AC8_13_160_ci_cd_distinguishes_canary_from_audit_replay` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |

### AC8.14: Product Trust Proof Mirrors

| AC ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC8.14.1 | Critical proof matrix classifies product proof paths by trust mode and source classes | `test_valid_behavioral_static_and_manual_entries_pass`, `test_AC8_14_1_critical_proof_matrix_reports_duplicate_proof_ids`, `test_AC8_14_2_llm_ocr_mirror_must_be_pr_deterministic` | `tests/tooling/test_check_critical_proof_matrix.py` | P0 |
| AC8.14.2 | Critical post-merge LLM/OCR product proofs must name a PR deterministic mirror proof for the same source classes | `test_AC8_14_2_llm_ocr_proof_requires_deterministic_pr_mirror`, `test_AC8_14_2_llm_ocr_mirror_must_be_pr_deterministic` | `tests/tooling/test_check_critical_proof_matrix.py` | P0 |
| AC8.14.3 | Personal report package critical proof has a deterministic PR mirror covering bank, brokerage, manual valuation, restricted-compensation, CSV, and manual-record source classes | `test_AC8_14_3_personal_package_has_deterministic_source_trust_mirror` | `tests/tooling/test_personal_report_package_fixture_contract.py` | P0 |
| AC8.14.4 | Backend reporting integration acts as a deterministic PR mirror from structured/manual source facts through ledger and core statements | `test_AC5_15_1_multicurrency_reporting_cycle_reconciles_bs_is_cf` | `apps/backend/tests/integration/test_reporting_e2e.py` | P0 |

### AC8.15: Full-Year Statement-to-Report End-to-End Acceptance

Closing gate for the **Usable** milestone (G2∩G3, [#950](https://github.com/wangzitian0/finance_report/issues/950)): AC8.14.4 mirrors the ledger→report leg from *manual* entries in a *single* period; this group proves the **assembled** pipeline — statement parse → Stage-1 approval (balance-chain validated) → auto-posted ledger entries → period reports — ties out across **multiple months**. Deterministic by construction (rule-based CSV parse, no LLM; no AI classification, so counter-accounts fall back to `Income - Uncategorized` / `Expense - Uncategorized`).

| AC ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC8.15.1 | Multi-month CSV statements parse, approve under the balance-chain guard, auto-post to the ledger, and the assembled period reports tie out end-to-end (income, expenses, net income, ending cash, total assets, and the accounting equation) | `test_AC8_15_1_full_year_statement_to_report_ties_out` | `apps/backend/tests/integration/test_full_year_statement_to_report_e2e.py` | P0 |
| AC8.15.2 | A high-confidence, balance-validated bank statement with no pre-selected account auto-creates+links its physical asset account (by institution + account_last4 + currency), reaches APPROVED, and auto-posts to the ledger — the everyday-user upload→report path no longer dead-ends in review (#1444) {tier:CODE-ONLY} | `test_AC8_15_2_bank_statement_auto_creates_account_and_posts_without_manual_mapping` | `apps/backend/tests/integration/test_bank_statement_auto_account_post.py` | P1 |

### AC8.16: Augmentation-Layer Report Integrity

AC8.14/AC8.15 pin the *core accounting arithmetic*. This group pins the newer
**augmentation layer** — confidence-tagged extracted/reconciled inputs and
append-only manual-valuation versioning — where the recent audit bugs lived
([#968](https://github.com/wangzitian0/finance_report/issues/968) superseded
valuation leaked into holdings; a missing `.distinct()` inflated provenance).
It stands up the *combined* state production actually has (a low-confidence ledger
input AND a corrected/superseded valuation present at once) and asserts the report
is right on every axis simultaneously. Part of [#990](https://github.com/wangzitian0/finance_report/issues/990) (report-input integrity).

| AC ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC8.16.1 | A low-confidence extracted ledger input and a corrected (superseded) manual valuation both reach the report correctly: ledger numbers and the accounting equation hold, the low-confidence line carries the worst-input tier (not laundered), the superseded valuation is excluded from net-worth components, and the manual valuation does not contaminate the ledger balance sheet | `test_AC8_16_1_augmentation_seam_excludes_superseded_and_surfaces_confidence` | `apps/backend/tests/integration/test_augmentation_seam_e2e.py` | P1 |
| AC8.16.2 | A report aggregates only the requesting user's facts: with posted entries for two users, user A's balance sheet, income statement, and net-worth totals reflect only A's data — user B's accounts never appear and never inflate a total (cross-user leak at the report-number level, now testable since the test schema keeps the `users` FK per #991) | `test_AC8_16_2_reports_exclude_other_users_entries` | `apps/backend/tests/integration/test_cross_user_report_isolation_e2e.py` | P1 |

**Traceability Ownership**:
- This table owns the intended AC-to-proof mapping for EPIC-008.
- Current AC counts, covered/untested totals, and placeholder/stub exclusions are
  owned by `python tools/analyze_test_ac_coverage.py --no-write --stdout` and
  CI traceability artifacts.
- Mandatory AC gate behavior is owned by `python tools/check_ac_index.py`.
- Test path execution status for AC proof is owned by
  [test-execution-matrix.yaml](../ssot/test-execution-matrix.yaml).
- Default AC traceability test-surface directories are owned by
  `common/testing/test_surface.py` and consumed by both the fail-closed gate and
  generated audit builder.
- Critical product proof-path anchoring is owned by
  the derived critical-proof matrix (macro outcome source `docs/ssot/critical-proof-outcomes.yaml`) and
  `python tools/check_ac_index.py`.
- Do not copy generated AC totals or per-group percentages into this EPIC.

---

### AC8.17: Test-Account Cleanup Tooling

Shared/staging databases accumulate throwaway accounts from QA and E2E runs
(`qa.*@example.com`, `e2e-*@test.example.com`, ...). This group covers the purge
library that reclaims them ([#997](https://github.com/wangzitian0/finance_report/issues/997)
item 4). The purge is **safe by construction**: each account is removed inside
its own savepoint (all-or-nothing), and an account still holding immutable
posted/reconciled ledger entries is *reported and skipped*, never force-deleted —
the same contract the API enforces with a 409 ([#988](https://github.com/wangzitian0/finance_report/issues/988)).

| AC ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC8.17.1 | Only disposable test accounts (qa/e2e/load-test prefixes on example.com / test.example.com) are selected; real accounts and plain local fixtures are excluded | `test_selection_matches_test_accounts_and_excludes_real_ones`, `test_owned_tables_cover_core_user_data_and_exclude_users` | `apps/backend/tests/services/test_test_account_purge.py` | P1 |
| AC8.17.2 | Applying the purge removes a clean test account and every row it owns, while leaving non-test accounts untouched | `test_apply_purges_clean_account_and_leaves_others` | `apps/backend/tests/services/test_test_account_purge.py` | P1 |
| AC8.17.3 | An account owning a posted (immutable) ledger entry is reported blocked and fully preserved, not force-deleted | `test_account_with_posted_ledger_entry_is_blocked_not_deleted` | `apps/backend/tests/services/test_test_account_purge.py` | P1 |
| AC8.17.4 | A dry run names the accounts it would purge but persists no deletions | `test_dry_run_reports_but_persists_nothing` | `apps/backend/tests/services/test_test_account_purge.py` | P1 |
| AC8.17.5 | The CLI `--apply` environment guard allows dev/staging/CI and refuses production (or an unset environment) without an explicit override | `test_environment_guard_allows_dev_staging_and_refuses_production` | `apps/backend/tests/services/test_test_account_purge.py` | P1 |

The operator entry point is `tools/purge_test_accounts.py` (dry-run by default;
`--apply` to delete; runbook in `docs/contributing/staging-test-account-cleanup.md`).

---

### AC8.18: Tier 2 Deployed HTTP E2E Proof Semantics

Tier 2 is the lightweight deployed-HTTP lane between Tier 1 in-process API E2E
and Tier 3 browser/provider-heavy E2E. It proves the deployed URL, routing,
version, public API reachability, frontend reachability, and unauthenticated
protection boundary through real HTTP. It is not a line-coverage input and a
not-run/env-gated advisory report is never proof eligible.

| AC ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC8.18.1 | The Tier 2 command fails closed unless a deployed base URL and expected deployed version are supplied | `test_AC8_18_1_tier2_http_command_fails_closed_without_deployed_inputs` | `tests/tooling/test_tier2_http_e2e.py` | P0 |
| AC8.18.2 | Tier 2 reports carry `proof_tier=tier2_http`; advisory/env-gated not-run output is marked `proof_eligible=false`, while passing reports require concrete HTTP checks | `test_AC8_18_2_tier2_http_report_is_proof_tiered_and_skip_ineligible`, `test_AC8_18_2_tier2_http_success_report_requires_real_http_checks`, `test_AC8_18_2_tier2_http_handles_non_object_health_json`, `test_AC8_18_2_tier2_http_accepts_short_and_full_sha_match` | `tests/tooling/test_tier2_http_e2e.py` | P0 |
| AC8.18.3 | Staging runs Tier 2 after shell smoke and before Tier 3/browser E2E, and the execution matrix names `deployment_tier2_http_e2e` separately | `test_AC8_18_3_staging_workflow_runs_tier2_http_before_tier3_browser_e2e`, `test_AC8_18_3_test_execution_matrix_names_tier2_http_stage` | `tests/tooling/test_tier2_http_e2e.py` | P0 |

### AC8.19: Login Auth-Control Accessibility Disambiguation

The login page exposes two controls that switch the form into register mode: a
segmented mode-toggle button and an inline call-to-action under the form. Both
read "Register" to users, which previously produced two buttons with the same
accessible name and broke Playwright strict-mode `get_by_role` locators. These
ACs require each control to carry a distinct, stable test hook and require the
registration E2E to target the mode toggle unambiguously, with no visible-copy
regression.

| AC ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC8.19.1 | Login auth controls (mode-toggle register button and inline register CTA) expose distinct `data-testid` hooks and accessible names, so no duplicate accessible-name ambiguity remains while the visible text stays "Register" | `AC8.19.1 login register controls expose distinct test ids and accessible names` | `apps/frontend/src/__tests__/loginPage.test.tsx` | P1 |
| AC8.19.2 | Registration E2E targets the mode-toggle register control by test id, switching into register mode without a strict-mode locator failure | `test_registration_api_path`, `test_full_registration_flow` | `tests/e2e/test_auth_flows.py` | P1 |

### AC8.20: PR Review Thread Merge Gate

A merge-time CI gate (issue #755 scope 2a) blocks a PR while a high-severity
review thread is still open. It reads the PR's review threads through the GitHub
GraphQL API (`gh api graphql`) and classifies each thread's severity from a
documented marker rule: a thread is **blocking (P0/P1)** when its first comment
body matches `\b(P0|P1)\b` (case-insensitive) or is Copilot-authored and not
explicitly marked a lower severity (`P2`/`P3`/`nit`); everything else is lower
severity. Only *unresolved* blocking threads fail the gate; resolved, outdated,
and lower-severity unresolved threads are reported but never block. The gate is
bootstrap-safe (a fresh PR with no unresolved P0/P1 passes) and skips cleanly on
non-PR events. The classification rule is owned by [ci-cd.md](../ssot/ci-cd.md).

| AC ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC8.20.1 | The checker blocks (exit 1) when an unresolved P0/P1 (or unresolved Copilot) review thread exists | `test_AC8_20_1_unresolved_p0_blocks`, `test_AC8_20_1_unresolved_copilot_blocks`, `test_AC8_20_1_blocking_thread_url_is_printed` | `tests/tooling/test_check_pr_review_threads.py` | P1 |
| AC8.20.2 | Resolved/outdated threads and lower-severity (P2/P3/nit) unresolved threads do NOT block; they are reported | `test_AC8_20_2_resolved_p0_passes`, `test_AC8_20_2_outdated_p0_passes`, `test_AC8_20_2_unresolved_nit_passes_but_reported`, `test_AC8_20_2_empty_passes`, `test_AC8_20_2_mixed_blocks_only_on_active_p0` | `tests/tooling/test_check_pr_review_threads.py` | P1 |
| AC8.20.3 | The severity classification rule is documented in the CI/CD SSOT | `test_AC8_20_3_severity_rule_documented_in_ssot` | `tests/tooling/test_check_pr_review_threads.py` | P1 |

---

### AC8.21: Seeded No-LLM Statement Journey (provider-free merge tier)

The statement review -> reconcile -> report journey previously needed a real
provider, so its LLM-independent DOM/CRUD/render assertions were stranded behind
`@pytest.mark.llm` mega-journeys that only run on the manual staging deploy —
letting selector/contract drift (and the empty-`original_filename` invisible-link
bug, #1142) slip past the merge gate. A `seeded_parsed_statement` fixture
(`apps/backend/tests/e2e/conftest.py`) injects an already-parsed statement —
ODS `UploadedDocument`, DWD `StatementSummary` (`status=PARSED`), and Layer-2
`AtomicTransaction` rows joined via `source_documents[*].doc_id` — directly into
the test database, bypassing the `ExtractionService.parse_document` -> `stream_ai_json`
seam entirely. The downstream journey then runs in the no-LLM merge-blocking tier
(`-m "... and not llm"`). This is the reusable enabler for moving the remaining
LLM-gated journeys (#1146 PR-B/PR-C) into CI; the browser/Playwright selector
fixes for `test_statement_upload_e2e` / `test_statement_full_journey` /
`test_four_asset_net_worth_golden_path` and the `_api_url(...)` fix in
`test_personal_financial_report_package` (#1142) are deferred to that follow-up,
which runs in the full-stack `preview.yml` lane that carries the frontend bundle.

| AC ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC8.21.1 | A seeded no-LLM fixture materializes an already-parsed statement (PARSED envelope, linked ODS document, atomic transactions, non-empty `original_filename`, Decimal balances) with zero provider calls, bypassing the extraction/LLM seam | `test_seeded_fixture_bypasses_provider` | `apps/backend/tests/e2e/test_seeded_statement_journey.py` | P0 |
| AC8.21.2 | The previously LLM-gated statement list -> detail journey runs in the no-LLM merge tier via the fixture: the list row and detail expose `status=parsed`, a non-empty `original_filename` (the stretched-link label, #1142), and the parsed transactions | `test_seeded_statement_list_and_detail_no_llm` | `apps/backend/tests/e2e/test_seeded_statement_journey.py` | P0 |
| AC8.21.3 | The seeded statement's transactions endpoint resolves the parsed atomic transactions (descriptions, Decimal amounts, directions) with no provider call, so the downstream review/reconcile journey runs provider-free | `test_seeded_statement_transactions_endpoint_no_llm` | `apps/backend/tests/e2e/test_seeded_statement_journey.py` | P0 |

### AC8.22: Test Execution Matrix as Code (testing-package governance)

Which tests run where was previously scattered: `docs/ssot/test-execution-matrix.yaml`
was hand-maintained, the PR preview E2E set was a hardcoded 2-file whitelist in
`preview.yml`, and marker semantics lived only in inline `-m` expressions —
so a non-LLM Tier-3 E2E gate was invisible pre-merge purely because nobody
added it to the whitelist (#1547). `common/testing/matrix.py` is now the SSOT
for test placement and selection (issue #1556): the docs YAML is its generated
view, every root E2E spec has a named ownership row (needs + audit status),
the pre-merge in-runner selection is derived (audited AND no external needs —
so an unaudited or provider-dependent spec can never silently enter the
merge-blocking path), and `preview.yml` consumes the selection at runtime via
`tools/test_selection.py --shell` instead of restating it. Charter:
`common/testing/README.md`; follow-ups: #1557 (all workflows + ci_tier↔JUnit
reconciliation), #1558 (package declaration rollout + mirror-assertion ratchet).

| AC ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC8.22.1 | The checked-in `docs/ssot/test-execution-matrix.yaml` is exactly the view generated from `common/testing/matrix.py` (byte-identical via the `--check-matrix` CLI gate), and the generated YAML parses into the same path→stage/ci_required rules the AC-traceability consumer reads — matrix-as-code cannot drift from the SSOT view {tier:CODE-ONLY} | `test_AC8_22_1_generated_matrix_matches_checked_in_yaml`, `test_AC8_22_1_generated_yaml_parses_identically_for_consumers` | `tests/tooling/test_execution_matrix_contract.py` | P0 |
| AC8.22.2 | `preview.yml` derives its in-runner E2E selection at runtime by eval'ing `tools/test_selection.py --stage pr_preview_e2e --shell` (tests, marker expression, parallelism all from the matrix) and carries no hardcoded `tests/e2e/` path — the #1547 whitelist is structurally impossible to reintroduce {tier:CODE-ONLY} | `test_AC8_22_2_preview_workflow_derives_selection_from_matrix` | `tests/tooling/test_execution_matrix_contract.py` | P0 |
| AC8.22.3 | The derived pre-merge selection contains exactly the audited, dependency-free rows (preserving the original in-runner set), every selected spec exists on disk, no `llm`-marked spec (verified against file content, not row metadata) can appear in the merge-blocking set, and the #1547 non-LLM vision hard gate is admitted after BOTH in-runner stack bugs it flushed out were root-caused and fixed in docker-compose.ci-e2e.yml — the double-/api NEXT_PUBLIC_API_URL 404 (PR #1587) and the #1589 FirstRunModal pointer interception (no provider wiring -> app-wide dismissible modal on every full navigation; fixed with placeholder wiring + unroutable AI_BASE_URL) — each admission a row flip, never a workflow edit {tier:CODE-ONLY} | `test_AC8_22_3_preview_selection_is_audited_and_dependency_free` | `tests/tooling/test_execution_matrix_contract.py` | P0 |
| AC8.22.4 | Every root `tests/e2e/test_*.py` spec has a named ownership row in the matrix (needs + audit status + reason) and no stale row survives file removal — an unclassified E2E spec fails CI instead of silently landing outside any execution tier {tier:CODE-ONLY} | `test_AC8_22_4_every_root_e2e_spec_has_a_named_row` | `tests/tooling/test_execution_matrix_contract.py` | P1 |
| AC8.22.5 | The `--shell` emission is valid, shlex-round-trippable bash (test array, quoted marker expression, parallelism) matching the in-code selection exactly, and an unknown stage is rejected with an explicit error {tier:CODE-ONLY} | `test_AC8_22_5_shell_emission_round_trips` | `tests/tooling/test_execution_matrix_contract.py` | P1 |
| AC8.22.6 | The testing-package governance charter (execution matrix, package declaration protocol, E2E extension layer, fast interception, responsibility table) exists in `common/testing/README.md`, and `docs/ssot/MANIFEST.yaml` records `common/testing/matrix.py` as the `test_execution_matrix` owner with the generated YAML as a cross-ref {tier:CODE-ONLY} | `test_AC8_22_6_charter_and_manifest_ownership` | `tests/tooling/test_execution_matrix_contract.py` | P1 |

### AC8.23: Workflow Selection Conformance & Execution Reconciliation

Follow-up to AC8.22 (issue #1557): marker expressions and test paths for every
junit-emitting pytest invocation across `.github/workflows/*.yml` now live once
in `common/testing/matrix.py` (`WORKFLOW_PYTEST_CONTRACTS`), enforced
fail-closed by a central conformance gate; and a declared `ci_tier="pr_ci"` on
an `@ac_proof` is reconciled against actual PR junit evidence in the
`ac-behavioral-ratchet` job — execution tier becomes a contract, not metadata.

| AC ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC8.23.1 | Every junit-emitting pytest invocation in any workflow is registered in the matrix contracts and every registered contract has exactly one live invocation — fail-closed in both directions, so a selection change is impossible without touching the SSOT {tier:CODE-ONLY} | `test_AC8_23_1_every_workflow_pytest_invocation_is_registered` | `tests/tooling/test_workflow_selection_conformance.py` | P0 |
| AC8.23.2 | Each registered invocation's `-m` expression and explicit path arguments equal the matrix constants (backend shards, integration, tier-1, staging core/provider/AI-OCR/version, production readonly) — marker semantics have exactly one owner {tier:CODE-ONLY} | `test_AC8_23_2_registered_invocations_match_matrix_selection` | `tests/tooling/test_workflow_selection_conformance.py` | P0 |
| AC8.23.3 | The staging AI/OCR corpus (derived from `@ac_proof` metadata) and the matrix llm rows describe the same provider-dependent spec set, with the connectivity probe as the only declared difference — the two derivations cannot drift silently {tier:CODE-ONLY} | `test_AC8_23_3_staging_ai_ocr_corpus_aligns_with_matrix_llm_rows` | `tests/tooling/test_workflow_selection_conformance.py` | P1 |
| AC8.23.4 | A behavioral `pr_ci` proof absent from aggregated PR junit evidence fails the reconciliation gate (wired after the score ratchet in ci.yml); present proofs pass, skipped-only is a hard fail (#1558: a pr_ci proof that only ever skips pre-merge is not executing its promise, though a skip in one shard with a real run in another passes), and parametrized/class-nested junit ids are matched correctly {tier:CODE-ONLY} | `test_AC8_23_4_pr_ci_evidence_reconciliation_gate`, `test_AC8_23_4_junit_parsing_handles_params_and_classes` | `tests/tooling/test_workflow_selection_conformance.py` | P0 |

### AC8.24: Package Test Declarations, Environment Preconditions & Mirror Ratchet

Series closer (issue #1558): domain packages declare the test roots they own
in their own `contract.py` (`TEST_ROOTS`), aggregated into the generated
execution-matrix view; E2E stages carry an explicit environment precondition
(runtime's smoke gate) that runs before any test so a red environment is never
attributed as a test failure; and the mirror-assertion stock is locked behind
an only-goes-down ratchet (`common/testing/mirror_ratchet.py`), stopping the
#1435 accretion.

| AC ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC8.24.1 | The seed packages (runtime, ledger, coverage) declare their owned test roots via `TEST_ROOTS` in their `contract.py`; the matrix aggregates them into the generated YAML's `ownership:` section (a dropped declaration fails the `--check-matrix` drift gate), every declared root exists on disk, and a root declared by two packages is rejected {tier:CODE-ONLY} | `test_AC8_24_1_seed_packages_declare_owned_test_roots`, `test_AC8_24_1_duplicate_declaration_is_rejected` | `tests/tooling/test_package_declaration_and_ratchet.py` | P0 |
| AC8.24.2 | Workflow pytest contracts declaring an environment precondition (the runtime-owned smoke gate, for the preview and staging core E2E stages) must run it before the pytest invocation in the same workflow — mechanized fault attribution: a red precondition aborts before tests start {tier:CODE-ONLY} | `test_AC8_24_2_e2e_stages_run_their_environment_precondition_first` | `tests/tooling/test_package_declaration_and_ratchet.py` | P0 |
| AC8.24.3 | The mirror-assertion count over `tests/tooling/` is locked behind a committed baseline that may only decrease: growth fails CI, `--update` refuses to raise the baseline, and paydown lowers it — with the eight marker-literal mirrors already redundant with AC8.23.2 deleted in the same change {tier:CODE-ONLY} | `test_AC8_24_3_mirror_assertion_ratchet_is_locked_and_only_goes_down` | `tests/tooling/test_package_declaration_and_ratchet.py` | P0 |

### AC8.26: Real Storage Pipeline (counted tier)

Issue #1520: every counted test stubbed the storage seam (DummyStorage /
mocked boto3), so the real ``StorageService`` wiring — upload, persist,
load-back — shipped unproven; green CI did not prove a user's statement
survives storage. These tests run the REAL service and the REAL
upload→store→parse pipeline against moto's in-memory S3 (no stub, no service
container, fast path), reusing the vision hard gate's deterministic CSV
fixture so the same business numbers are proven at the counted tier. Their
first run caught a live production bug: the success path persisted the bare
display filename as ``UploadedDocument.file_path``, so every post-success
retry/reparse fetched a nonexistent storage key (fixed in
``statement_parsing.py`` alongside).

| AC ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC8.26.1 | A CSV fixture uploads through ``/statements/upload`` with the REAL StorageService into in-memory S3 (env-level config only — the service is never stubbed or patched), the pipeline parses it, the stored object read back via the real ``get_object`` is byte-identical to the fixture, and the resolved transactions carry the fixture's known business values (6 transactions, 11200.00 gross) {tier:CODE-ONLY} | `test_AC8_26_1_upload_parses_through_real_storage_round_trip` | `apps/backend/tests/api/test_real_storage_pipeline.py` | P0 |
| AC8.26.2 | The retry path re-fetches the source document through the real ``get_object`` (the load-back leg the in-process first parse skips — this is the assertion that caught the file_path production bug), and deleting the stored object makes retry fail instead of parsing a cached copy — proving the pipeline truly reads storage {tier:CODE-ONLY} | `test_AC8_26_2_retry_loads_source_back_through_real_storage` | `apps/backend/tests/api/test_real_storage_pipeline.py` | P0 |

## 5. E2E Suite Ownership

Current test counts and coverage percentages belong to generated reports and CI
artifacts, not this EPIC. This section records which suites are allowed to
serve as E2E proof surfaces.

### 5.0 Env x Stage Delivery Matrix

CI/CD proof is modeled as a sparse environment x pipeline stage matrix, not as a
linear list of delivery stages. Environments define where proof runs; pipeline
stages define what quality gate runs. Empty cells are intentional and must not
be filled just for symmetry.

| Env \ Stage | Changed/Affected UT | Lint/Static | Full UT | Integration | Regression/E2E | Image Build | Deploy Smoke | Provider Gate | Release Integrity |
|---|---|---|---|---|---|---|---|---|---|
| `local` | default | focused/static contracts | risk-triggered only | risk-triggered only | not default | no | no | no | no |
| `pr` | covered by full gates | required | required for heavy changes | required for heavy changes | Tier-1/provider-free required for heavy changes | dry-run for heavy changes | no | no | no |
| `pr-preview` | no | no | no | no | runtime/UI/API preview-relevant subset after successful PR CI | no PR images | runner `/api/health` + smoke/E2E | no | no |
| `staging` | no | no | no | no | merged-SHA non-LLM plus provider-backed regression when required | reuse or build missing SHA images | required | runs when real provider proof is required | no |
| `prd` | no | no | no | no | prod-safe smoke only | release image proof | required | no first-time proof | required |

Operational interpretation:
- Local optimizes left-shift speed and runs affected/focused checks by default,
  not full remote-equivalent CI.
- PR CI is the deterministic merge authority for business behavior, coverage,
  traceability, and image build proof.
- PR preview proves the PR head can boot, route through the runner edge, report
  the expected version, and pass provider-free smoke/E2E after the matching PR
  CI succeeds; it no longer creates PR preview images or a persistent Dokploy
  URL.
- Staging consumes only successful `main` SHAs, always proves real infra and
  non-LLM deployed behavior for deploy-relevant changes, and runs provider
  proof only when real provider evidence is required for AI/OCR, extraction,
  statement parsing, PDF fixture, or critical LLM proof changes.
- Production proves release integrity and availability; it must not be the first
  proof of deterministic business correctness.

### 5.1 E2E Proof Surface Ownership

E2E file inventories and Tier-1 test-to-AC mappings are generated or validated
by tooling instead of being copied into this EPIC:

| Fact | Owner |
|---|---|
| Test path -> execution stage mapping | [test-execution-matrix.yaml](../ssot/test-execution-matrix.yaml) |
| Product E2E function -> EPIC ownership | `tools/check_e2e_epic_traceability.py` |
| Mandatory AC proof eligibility | `tools/check_ac_index.py` |
| Critical macro outcome proof | `tools/check_ac_index.py` (derived view of [critical-proof-outcomes.yaml](../ssot/critical-proof-outcomes.yaml)) |

Product E2E ownership index:

| File | Ownership anchor |
|---|---|
| `apps/backend/tests/e2e/test_auth_flows.py` | Backend auth flow E2E; AC references live in the test file |
| `apps/backend/tests/e2e/test_core_journeys.py` | Backend core journey E2E; AC8.1-AC8.12 references live in the test file |
| `apps/backend/tests/e2e/test_e2e_flows.py` | Backend extended flow E2E; AC references live in the test file |
| `apps/backend/tests/e2e/test_epic022_ia.py` | EPIC-022 everyday-user IA shell product owner E2E; AC22.1 references live in the test file |
| `apps/backend/tests/e2e/test_epic025_dry_ssot_e2e.py` | EPIC-025 DRY/SSOT product owner E2E; AC25.1.1 (reporting_calc extraction is behavior-preserving) references live in the test file |
| `apps/backend/tests/e2e/test_statement_corpus_journeys.py` | Extraction-corpus merge-tier E2E; ACs live in the `llm` package roadmap (AC-llm.10, `common/llm/contract.py`) |
| `tests/e2e/test_ac_authority_tiers_epic026.py` | EPIC-026 authority-tier pipeline product owner E2E; AC-authority.2.1/AC-authority.3.1/AC-authority.4.1 references live in the test file |
| `tests/e2e/test_application_ai_advisor_epic021.py` | Application AI Advisor product owner E2E; AC21.1 references live in the test file |
| `tests/e2e/test_auth_flows.py` | Deployed auth flow E2E; AC references live in the test file |
| `tests/e2e/test_brokerage_upload_to_portfolio_value.py` | Critical proof: AC8.13.10 |
| `tests/e2e/test_core_journeys.py` | Deployed core journey E2E; AC references live in the test file |
| `tests/e2e/test_e2e_flows.py` | Deployed extended flow E2E; AC references live in the test file |
| `tests/e2e/test_four_asset_net_worth_golden_path.py` | Critical proof: AC8.13.42, AC8.13.10, AC5.7.3, AC11.9.1-AC11.9.3, AC17.5.4 |
| `tests/e2e/test_llm_provider_abstraction_epic023.py` | LLM provider abstraction product owner E2E; EPIC-023 / AC23.1 references live in the test file |
| `tests/e2e/test_frontend_observability_epic024.py` | EPIC-024 frontend browser observability product owner E2E; AC24.1.1 reference lives in the test file |
| `tests/e2e/test_market_data_price_paths.py` | Critical proof: AC11.10.7, AC11.10.11 |
| `tests/e2e/test_personal_financial_report_package.py` | Critical proof: AC5.1.1, AC5.1.4, AC5.2.3, AC5.3.1, AC5.8.1, AC5.12.4, AC5.13.4-AC5.13.5, AC11.8.3, AC11.9.1-AC11.9.3, AC11.11.1-AC11.11.2, AC17.10.1-AC17.10.2, AC17.12.1-AC17.12.3, AC8.13.83-AC8.13.85, AC8.13.87-AC8.13.88 |
| `tests/e2e/test_production_readonly_smoke.py` | Production-readonly smoke E2E; AC references live in the test file |
| `tests/e2e/test_statement_full_journey.py` | Critical proof: AC8.13.1-AC8.13.5 |
| `tests/e2e/test_statement_upload_e2e.py` | Statement upload E2E; AC references live in the test file |
| `tests/e2e/test_version_check.py` | Version/runtime E2E; AC references live in the test file |
| `tests/e2e/test_vision_upload_to_dashboard_hard_gate.py` | Critical proof: AC8.13.28-AC8.13.32 |

Product E2E files under `tests/e2e/test_*.py` and
`apps/backend/tests/e2e/test_*.py` must carry AC references directly. They are
not eligible for `docs/project/traceability-exceptions.md`; only fixtures and
shared harness files may use that exception path. The `repo/e2e_regressions/`
tree belongs to the `repo/` infra2 submodule and is managed by the infrastructure
submodule sync process.

### 5.2 CI Simplification Decision Log

- 2026-06-10: Keep the Env×Stage matrix as the primary control plane and keep
  legacy scalar outputs (`heavy_required`, `pr_preview_required`, `staging_required`,
  `staging_ai_ocr_required`) as temporary compatibility shims only. This is a
  controlled simplification path because external branch protection and ad hoc
  consumers can still depend on them while all GitHub Actions jobs consume
  `env_stage_required`, `env_stage_reasons`, and provider gate matrices.
- 2026-06-10: `PR Test Environment` now uses a stable per-PR canonical URL
  (`report-pr-<pr>.<domain>`) with commit-scoped aliases preserved for backward
  compatibility. This closes #783 and is now documented through AC8.13.101.
- 2026-06-12: PR preview follows successful PR `CI` `workflow_run` events and
  runs only a runner-local full-stack preview. PR image build/push/preflight and
  immediate PR image deletion were removed; legacy Dokploy resources are
  cleanup-only.
- 2026-06-23: Completed the migration — the per-env legacy scalar outputs
  (`pr_preview_required`, `staging_required`, `staging_ai_ocr_required`) are no
  longer emitted by `ci_change_classifier`. The 2026-06-10 precondition was met
  (all GitHub Actions consumers normalize from the structured matrix; required
  contexts are keyed on job names, not classifier step outputs), so Residual A
  is removed. `heavy_required` and `reason` are retained as top-level scalars,
  and the human-readable job summary still prints per-env lines.

### 5.6 Residual Drift to Simplify Next

- **Residual A: Compatibility scalar outputs — ✅ DONE (2026-06-23)**
  - The per-env scalars (`pr_preview_required`, `staging_required`,
    `staging_ai_ocr_required`) are no longer emitted by `ci_change_classifier`;
    the structured Env×Stage / provider-gate JSON is the sole machine-readable
    gate contract. `heavy_required` and `reason` are retained as top-level
    scalars (the PR heavy gate is also expressed as `env_stage_required.pr`).
  - All GitHub Actions consumers normalize their own scalar from the structured
    matrix, so no migration shim remained.

- **Residual B: Legacy gate normalization step wrappers**
  - `preview.yml` and `deploy.yml` still deserialize
    `env_stage_required` and `provider_gate_required` into legacy scalar outputs
    before job-level `if:` checks.
  - Functionally correct, but it adds one wrapper hop and keeps the code path
    slightly non-linear.

- **Residual C: Unused matrix dimensions in runtime decisions**
  - `env_stage_stages` and `env_stage_files` are currently used for reporting and
    audit evidence, not as direct runtime gating inputs.
  - The CI now remains correct because each workflow only consumes the stage
    cells it owns, but this is a traceability-complete model versus strict
    direct-gate-driven model.

The simplification priority remains:

1. Remove Residual B (single-step expression gating from structured outputs).
2. ~~Remove the per-env scalar shims (Residual A)~~ — **done 2026-06-23**.
3. Add a narrow enforcement test that each lane consumes only matrix cells it
   is authorized for, and that unused matrix dimensions are intentionally
   read-only.

### 5.3 CI Logic Review Findings

- Current CI logic is logically consistent with the target sparse Env×Stage model:
  `ci.yml` follows `pr` gates for deterministic behavior and coverage,
  `preview.yml` follows `pr-preview` gates for scoped preview deployment, and
  `deploy.yml` with `target=staging` follows `staging` + provider gates for
  post-merge infra and provider replay.
- The per-env scalar shims have been retired (2026-06-23); the remaining
  complexity is the small per-workflow normalization glue (Residual B) that
  deserializes the structured matrix into a local scalar before job-level `if:`
  checks. That glue is functionally correct and is the next simplification
  boundary.
- Logging sufficiency check is favorable: every critical stage emits both context
  artifacts and step-level classification/failure-domain breadcrumbs before exit
  (`pr-preview-readiness-context.json`, `staging-deploy-context.txt`,
  `staging-ai-ocr-context.txt`, coverage and traceability summaries).

#### 5 counterfactual assumptions + 5 operational guardrails

1. If PR preview was still using commit-only hostnames, old `report-pr-<pr>.<domain>`
   readers would still pass only by route alias mismatch: fixed by AC8.13.101.
2. If `ci_change_classifier` regressed to `docs`-only heavy skip for runtime
   paths, PR CI would stop running backend/frontend/e2e for changed runtime files.
3. If `env_stage_required` drifted from job conditions, merge authority would
   pass with missing deterministic stages; current tests assert every PR heavy job
   consumes the same matrix gate.
4. If route/readiness loops never produced root-cause labels, incident triage would
   degrade; failure-domain classification is now explicit in readiness/probe and
   staging deploy failure scripts.
5. If provider-backed flows were not isolated, quota bleed and non-deterministic
   retries would dominate; provider gate is explicit and runs only on AI/OCR-relevant
   changes.
6. If stale resources were not captured, next run latency would accumulate;
   current controls cover PR previews, GHCR tag pruning, host hygiene
   (infra2-owned), and stale version visibility in deployment context.
7. The in-runner E2E gate runs synchronously on `pull_request`, not asynchronously
   via `workflow_run`: a `workflow_run` gate fires only after CI, so a fast or auto
   merge could land before it ran — and GitHub counts a skipped required check as
   passed, which made the "merge authority" bypassable. A synchronous `pull_request`
   check must pass before merge. (The heavier persistent preview stays on-demand via
   `workflow_dispatch`; the gate is image-free so it needs no CI artifact.)
8. If staging consumed PR-head SHAs instead of successful `main` merge SHAs, deploy
   reproducibility and release provenance would weaken; staging tracks workflow_run
   SHA and uses successful main SHA gates.
9. If production ran first-time business proof, regression risk would shift to runtime
   after user impact; production remains integrity + availability-only, after all
   prior gates.
10. If unknown failure classes dropped out of failure mapping, triage would get
   slower; both staging and preview scripts retain fallback context dumps before final
   failure.

### 5.4 CI/CD Integration Ownership

Workflow status is not hand-maintained here. CI structure, smoke-test placement,
critical proof checks, and environment isolation are owned by
[ci-cd.md](../ssot/ci-cd.md), `.github/workflows/*.yml`, and the corresponding
tooling tests.

### 5.5 Known Gaps

Known testing gaps are not maintained as detailed status narratives here. Use
these owners instead:

| Gap type | Owner |
|---|---|
| Personal report package proof contract | `tools/check_ac_index.py` (derived view; macro outcome source [critical-proof-outcomes.yaml](../ssot/critical-proof-outcomes.yaml)), #573/#649, `tests/tooling/test_personal_report_package_fixture_contract.py` |
| Provider-backed staging AI/OCR gates | [ci-cd.md](../ssot/ci-cd.md), staging workflow artifacts |
| Manual-verification treatment | [issue #454](https://github.com/wangzitian0/finance_report/issues/454) |
| Generated README/project metrics | [issue #455](https://github.com/wangzitian0/finance_report/issues/455) |
| Future observability, visual regression, and performance gates | AC8.13.61-AC8.13.63 |

If a gap should block CI, encode it in a workflow/tool check and add AC proof.
If it is only a roadmap item, keep it in issues rather than prose status.

### 5.5 Running Tests

```bash
# Run root deployment E2E tests locally
moon run :test -- --e2e

# Run Tier 1 API E2E tests (requires DB)
moon run :test -- --backend-e2e

# Run against specific environment
APP_URL=https://report.zitian.party pytest tests/e2e -v -m "smoke or e2e"

# Run smoke tests only (fast)
bash tools/smoke_test.sh http://localhost:3000 dev

# Run with UI visible (debugging)
HEADLESS=false pytest tests/e2e -v
```

## 6. Archive Integration Notes

Removed testing archive content is retained in [issue #548](https://github.com/wangzitian0/finance_report/issues/548)
and git history. Current truth is owned by the active README -> EPIC -> AC ->
test chain, the critical proof matrix, generated registries, generated CI
artifacts, and coverage policy code.

### 6.1 Archive Residual Backlog Ownership

| Residual | Owner AC | Current boundary |
|---|---|---|
| Visual regression | AC8.13.61 | P3 future testing capability; add a visual gate only when visual stability becomes a release requirement |
| Test observability: test report dashboard, failure notification, and trend analysis | AC8.13.62 | Current replacements are GitHub Step Summary, CI artifacts, Coveralls, and generated coverage reports |
| Performance testing | AC8.13.63 | Locust exists; promote to a required P95 gate only after threshold ownership and failure policy are defined |

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [../ssot/coverage.md](../ssot/coverage.md) — coverage policy semantics.
- [../ssot/ci-cd.md](../ssot/ci-cd.md) — CI gate semantics.
- Environment smoke-test rationale and command semantics — migrated out of this EPIC into the `runtime` package: [../../common/runtime/readme.md](../../common/runtime/readme.md).
- [Backend tests README](https://github.com/wangzitian0/finance_report/blob/main/apps/backend/tests/README.md) — backend test-suite navigation.

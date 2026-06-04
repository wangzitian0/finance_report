# EPIC-008: Comprehensive Testing Strategy (Smoke & E2E)

> **Status**: ✅ Core Complete
> **Vision Anchor**: `decision-filter-accuracy-auditability`
> **Owner**: QA / DevOps
> **Date**: 2026-01-16
> **Updated**: 2026-05-29

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
| Unit (Fast/Shard) | Backend tests excluding `slow`, `e2e`, and `integration` markers | Required on `main`/heavy PR after integration/Tier-1 gates pass: `backend` job, 6-way shard, `-m "not slow and not e2e and not integration"` | Contributes to unified line coverage (backend part), AC traceability generation, and baseline no-regression gate |
| Integration (backend) | Backend tests marked `integration` | Explicit CI stage: `backend-integration` job, marker-scoped and service-backed | Not included in unified coverage by default; AC proof channel only |
| Tier 1 API E2E (`-m e2e`) | `apps/backend/tests/e2e/test_core_journeys.py` ASGI/API contract flows | Explicit CI stage: `backend-e2e-tier1` job with marker override and explicit Tier-1 scope | Behavioral proof for ACs and regression risk; **not included in unified line coverage** |
| Frontend Playwright | Provider-free specs under `apps/frontend/playwright` | Explicit CI stage inside the `frontend` job after build and Vitest; env-gated specs are not required proof | Browser UI behavioral proof only, not part of unified line coverage |
| Tier 2 HTTP E2E | Deploy-aware HTTP-level flows in staging/prod | Not a CI-shard job today; kept for staged/manual/prod smoke command evolution | Behavioral proof only, not part of unified line coverage |
| Tier 3 Browser E2E | `tests/e2e` Playwright/browser scenarios | Post-merge staging/prod gates and PR preview where appropriate | Behavioral proof only; AC pass rate requires real pass (skip and stub-only do not count) |

### Stage-by-Stage Semantics

| Metric | Definition | Data source | Regression gate behavior |
|---|---|---|---|
| Unified Line Coverage | `(sum covered LF) / (sum executable LF)` over unified files only | `coverage/backend.lcov`, `coverage/frontend.lcov`, `coverage/common.lcov`, `coverage/tools.lcov` after policy mapping | No-regression vs `unified-coverage.json`; line-based only |
| AC Pass Rate | `(ACs with at least one passing qualifying test) / (Total ACs)` | Generated AC coverage audit report | Informational for behavior completeness; not a line-coverage substitute |
| AC Traceability Gate | Real AC references in CI-required execution stages | `tools/check_ac_traceability.py`, `docs/ssot/test-execution-matrix.yaml`, `tools/check_e2e_epic_traceability.py` | Fail closed when mandatory AC is missing, stub-only, placeholder-only, or real-only outside required execution |

AC rates are generated on each CI run from `python tools/analyze_test_ac_coverage.py` inputs and do not mean line coverage. If a number changes, it is an AC definition or behavior-proof change, not automatically a line-coverage baseline change.

Current test and AC coverage status is generated, not hand-maintained here.
Use `python tools/analyze_test_ac_coverage.py --no-write --stdout`,
`docs/analysis/ac-epic-mismatch-report.md`, and CI artifacts for live proof
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
| Critical E2E proof paths | [critical-proof-matrix.yaml](../ssot/critical-proof-matrix.yaml) |
| Product E2E function ownership | `tools/check_e2e_epic_traceability.py` |
| AC proof and placeholder/stub exclusion | `tools/check_ac_traceability.py`, CI traceability artifact |

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

### AC8.1: Smoke Tests (Health Checks)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.1.1 | API health check | `test_api_health_check()` | `e2e/test_core_journeys.py` | P0 |
| AC8.1.2 | Backend service reachable | `test_backend_service_reachable()` | `e2e/test_core_journeys.py` | P0 |
| AC8.1.3 | Frontend service reachable | `test_frontend_api_proxy_reachable()` | `e2e/test_core_journeys.py` | P0 |
| AC8.1.4 | Database connectivity | `test_database_connectivity()` | `e2e/test_core_journeys.py` | P0 |

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
| AC8.10.8 | User registration flow | `test_traceability_user_registration()` | `e2e/test_core_journeys.py` | P0 |
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
| AC8.13.10 | Multi-brokerage PDF upload → position import → latest portfolio value | `test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value`, `test_statement_import_flows_to_holdings_and_balance_sheet`, `test_parse_document_routes_brokerage_balance_mismatch_to_parsed` | `tests/e2e/test_brokerage_upload_to_portfolio_value.py`, `apps/backend/tests/portfolio/test_brokerage_position_parsing.py`, `apps/backend/tests/extraction/test_statement_brokerage_import_bridge.py` | P0 |
| AC8.13.11 | Staging health check diagnoses API route 404 with route probes | `test_AC8_13_11_health_check_diagnoses_staging_api_route_404` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.12 | AI/OCR gate failures include statement validation context | `test_AC8_13_12_ai_ocr_gate_failure_includes_statement_context` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.13 | Staging deploy cancels stale runs and bounds E2E gate duration with phase timing logs | `test_AC8_13_13_staging_deploy_fast_fail_guardrails` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.14 | Provider-backed staging AI/OCR gate runs separately from deploy health | `test_AC8_13_14_staging_ai_ocr_gate_is_separate_deploy_job` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.15 | Unified coverage policy keeps CI source tree, LCOV reports, and Coveralls uploads aligned | `test_*coverage_policy*` / `test_build_unified_lcov*` | `tests/tooling/` | P0 |
| AC8.13.16 | CI change classification skips backend/frontend/coverage for lightweight changes and uses deterministic npm cache | `test_AC8_13_16_ci_change_classification_and_frontend_cache` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.17 | AC registry generation writes small generated indexes, materializes entries from EPIC docs plus explicit overrides, and preserves no duplicate feature/infra ownership | `test_main_appends_missing_ac_without_rewriting_current_epic_text` / `test_main_materialized_registries_have_no_duplicate_or_missing_ids` / `test_AC8_13_17_ac_traceability_runs_registry_generation_check` | `tests/tooling/test_generate_ac_registry.py` / `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.18 | Brokerage portfolio gate validates market valuation adjustment lines even when unrelated asset lines lower total assets | `test_portfolio_valuation_gate_ignores_unrelated_negative_asset_lines` / `test_portfolio_market_adjustment_survives_unrelated_negative_asset_lines` | `tests/e2e/test_brokerage_upload_to_portfolio_value.py` / `apps/backend/tests/reporting/test_reporting_net_worth_components.py` | P0 |
| AC8.13.19 | Brokerage portfolio gate failures include holdings, valuation adjustment, non-portfolio asset, and balance-sheet diagnostics | `test_portfolio_valuation_gate_failure_diagnostics_are_actionable` | `tests/e2e/test_brokerage_upload_to_portfolio_value.py` | P0 |
| AC8.13.20 | CI change classification is covered by multi-commit and markdown edge-case regression tests | `test_AC8_13_20_*` | `tests/tooling/test_ci_change_classifier.py` | P1 |
| AC8.13.21 | Provider-backed post-merge AI/OCR gate runs only after a successful main CI `workflow_run` | `test_AC8_13_21_post_merge_ai_ocr_requires_successful_ci_workflow_run` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.22 | Staging deploy starts from successful main CI `workflow_run` before building or deploying | `test_AC8_13_22_staging_deploy_starts_from_successful_ci_before_building` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.23 | Automatic staging deploy health and AI/OCR validation run in one serialized post-merge workflow unit | `test_AC8_13_23_post_merge_deploy_and_ai_ocr_are_one_serial_unit` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.24 | AC traceability audit is uploaded as a CI artifact instead of failing on a stale committed report | `test_AC8_13_24_ac_traceability_uploads_audit_artifact_without_stale_doc_gate` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.25 | Backend tests and AC traceability start without waiting for lint when their own prerequisites are ready | `test_AC8_13_25_backend_and_traceability_do_not_wait_for_lint` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.26 | CI metrics contract fails when source roots, coverage policy, workflow gates, or AC traceability semantics drift | `test_AC8_13_26_*` | `tests/tooling/` | P0 |
| AC8.13.27 | Pull requests do not publish Coveralls status contexts; main-only Coveralls reporting remains separate from local deterministic coverage gates | `test_AC8_13_27_*` | `tests/tooling/` | P0 |
| AC8.13.28 | Deterministic upload-to-dashboard gate runs as a critical fresh-user staging E2E | `test_statement_upload_to_dashboard_vision_hard_gate` | `tests/e2e/test_vision_upload_to_dashboard_hard_gate.py` | P0 |
| AC8.13.29 | Stage 1 review auto-posts journal entries from the deterministic fixture | `test_statement_upload_to_dashboard_vision_hard_gate` | `tests/e2e/test_vision_upload_to_dashboard_hard_gate.py` | P0 |
| AC8.13.30 | Reconciliation rerun is idempotent and Stage 2 run review reaches a cleared completion state | `test_statement_upload_to_dashboard_vision_hard_gate` | `tests/e2e/test_vision_upload_to_dashboard_hard_gate.py` | P0 |
| AC8.13.31 | Processing Account summary and pending page stay visible and correct for the cleared run | `test_statement_upload_to_dashboard_vision_hard_gate` | `tests/e2e/test_vision_upload_to_dashboard_hard_gate.py` | P0 |
| AC8.13.32 | Dashboard, balance sheet, income statement, and cash-flow totals exactly match the deterministic upload fixture | `test_statement_upload_to_dashboard_vision_hard_gate` | `tests/e2e/test_vision_upload_to_dashboard_hard_gate.py` | P0 |
| AC8.13.33 | Shared E2E setup caches Python virtualenv and Playwright browser artifacts for staging and preview gates | `test_AC8_13_33_e2e_setup_caches_virtualenv_and_playwright_browsers` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.34 | CI and post-merge workflows append queue, execution, and per-job timing summaries to GitHub Step Summary | `test_AC8_13_34_*` | `tests/tooling/` | P1 |
| AC8.13.35 | AC traceability reporting distinguishes real test references from `_ac_stubs` and trivial placeholder assertions | `test_classifies_placeholder_assertion`, `test_classifies_pure_pass_ac_file_as_placeholder`, `test_classifies_ac_stub_directory`, `test_placeholder_and_stub_refs_do_not_count_as_real_coverage` | `tests/tooling/test_check_ac_traceability.py` | P0 |
| AC8.13.36 | Main CI builds SHA-tagged staging images and post-merge staging reuses them after CI workflow success | `test_AC8_13_36_post_merge_reuses_sha_tagged_staging_images` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.37 | AC traceability fails mandatory ACs that are covered only by `_ac_stubs` | `test_returns_one_with_stub_only` | `tests/tooling/test_check_ac_traceability.py` | P0 |
| AC8.13.38 | Scheduled PR preview cleanup removes stale closed-PR VPS resources while preserving open PR previews | `test_AC8_13_38_*` | `tests/tooling/test_cleanup_pr_preview_resources.py` | P0 |
| AC8.13.39 | Runtime and container versions stay aligned across local, CI, and Docker environments | `test_AC8_13_39_*` | `tests/tooling/test_toolchain_contract.py` | P0 |
| AC8.13.40 | PR CI dry-runs staging image builds before merge; main push CI is the only path that pushes SHA-tagged images | `test_AC8_13_40_pr_ci_dry_runs_staging_image_builds_before_merge` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.41 | Critical proof matrix fails when a core product proof path is backed only by broad or reference-only AC strings | `test_*critical_proof_matrix*` | `tests/tooling/test_check_critical_proof_matrix.py` | P0 |
| AC8.13.42 | Four-asset as-of net worth golden path runs as a critical fresh-user post-merge E2E | `test_four_asset_as_of_net_worth_golden_path`, `test_AC8_13_42_four_asset_net_worth_golden_path_is_post_merge_critical` | `tests/e2e/test_four_asset_net_worth_golden_path.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.43 | Failed main CI workflow_run reports current staging state without deploying | `test_AC8_13_43_failed_ci_workflow_run_reports_no_deploy_diagnostic` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.44 | Local bootstrap provides one command for runtimes, dependency setup, pre-commit hooks, and container-runtime diagnostics | `test_AC8_13_44_*` | `tests/tooling/test_bootstrap_local.py`, `tests/tooling/test_cli_and_dev_servers.py`, `tests/tooling/test_toolchain_contract.py` | P0 |
| AC8.13.45 | Local verification entry points fail on the same backend format errors and route `make test` through the root Moon test command without hashing the infra submodule gitlink as a file input | `test_AC8_13_45_*` | `tests/tooling/test_cli_and_dev_servers.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.46 | PR preview non-LLM E2E uses the same strict, parallel gate shape as staging non-LLM E2E | `test_AC8_13_46_pr_preview_non_llm_gate_matches_staging_strict_parallelism` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.47 | Remaining delivery-engine optimizations are captured in a tracked project recommendation note | `test_AC8_13_47_delivery_engine_recommendations_are_tracked` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.48 | Frontend gap tests cover route, component, and API helper paths so frontend LCOV line coverage reaches 99% | `test_AC8_13_48_*` | `apps/frontend/src/__tests__/stage2ReviewQueueCoverage99.test.tsx`, `apps/frontend/src/__tests__/statementReviewPage.coverage.test.tsx`, `apps/frontend/src/__tests__/statementDetailPage.coverage.test.tsx`, `apps/frontend/src/__tests__/StatementUploader.test.tsx`, `apps/frontend/src/__tests__/journalPage.test.tsx`, `apps/frontend/src/__tests__/reconciliationWorkbenchComponent.test.tsx`, `apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx`, `apps/frontend/src/__tests__/apiFunctions.test.ts`, `apps/frontend/src/__tests__/accountsPage.test.tsx`, `apps/frontend/src/__tests__/assetsPage.test.tsx`, `apps/frontend/src/__tests__/statementsPage.test.tsx`, `apps/frontend/src/__tests__/useWorkspaceHook.test.tsx`, `apps/frontend/src/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx`, `apps/frontend/src/__tests__/uiGapAudit.netWorthTimeSeries.test.tsx`, `apps/frontend/src/__tests__/uiGapAudit.processingVisibility.test.tsx` | P0 |
| AC8.13.49 | Staging AI/OCR gates publish audit input inventory and replay summary fields | `test_AC8_13_49_staging_ai_ocr_gate_publishes_audit_inventory_and_summary` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.50 | Critical proof matrix validates the closed macro outcome set from README through owner EPICs and E2E proof anchors | `test_AC8_13_50_*` | `tests/tooling/test_check_critical_proof_matrix.py` | P0 |
| AC8.13.51 | Automatic staging deploy uses successful main CI `workflow_run`, with no in-job CI polling | `test_AC8_13_51_staging_deploy_starts_after_successful_ci_workflow_run` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.52 | Production release dry-run validates release prerequisites and image builds without production mutation | `test_AC8_13_52_production_release_dry_run_does_not_mutate_production` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.53 | Common owns SSOT, config and CI contracts, coverage policy, and isolation helpers; command entry points and tool-owned implementations live in `tools/` | `test_AC8_13_53_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_ci_metrics_contract.py` | P0 |
| AC8.13.54 | Critical proof matrix fails when README macro outcomes, matrix outcomes, or owner EPIC reverse declarations drift | `test_AC8_13_54_*` | `tests/tooling/test_check_critical_proof_matrix.py` | P0 |
| AC8.13.55 | Post-merge staging deploys only for runtime, deploy, E2E, staging workflow, toolchain, or infra-submodule changes | `test_AC8_13_55_*` | `tests/tooling/test_ci_change_classifier.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.56 | Coverage command entry points run from `tools/`; the shared policy stays in `common/coverage/policy.py`, and command implementations live under `tools/_lib/coverage/` | `test_AC8_13_56_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_ci_metrics_contract.py`, `tests/tooling/test_coverage_policy.py`, `tests/tooling/test_build_unified_lcov.py` | P0 |
| AC8.13.57 | SSOT and AC command entry points run from `tools/` while shared implementations live under `common/ssot/` | `test_AC8_13_57_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_ci_metrics_contract.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.58 | CI and toolchain command entry points run from `tools/`; reusable contracts stay under `common/ci/`, while report and shell command implementations live under `tools/_lib/` | `test_AC8_13_58_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_toolchain_contract.py`, `tests/tooling/test_ci_change_classifier.py`, `tests/tooling/test_github_workflow_timing_summary.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.59 | Config validation command entry points run from `tools/` while shared implementations live under `common/config/` | `test_AC8_13_59_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_check_env_keys.py`, `tests/tooling/test_validate_schemas.py` | P0 |
| AC8.13.60 | Deploy workflows do not keep no-op dependency checks or warning-only performance probes that cannot block release risk | `test_AC8_13_60_deploy_workflows_have_no_nonblocking_noop_gates` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.61 | Visual regression residual is explicitly owned by EPIC-008 as a P3 future testing capability | `test_AC8_13_61_visual_regression_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P3 |
| AC8.13.62 | Test observability residuals are explicitly owned by EPIC-008 with current replacements and future dashboard/notification/trend scope | `test_AC8_13_62_test_observability_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P2 |
| AC8.13.63 | Performance testing residual is explicitly owned by EPIC-008 with current Locust/staging coverage and future P95 trend gate scope | `test_AC8_13_63_performance_testing_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P2 |
| AC8.13.64 | Production release verifies DB, S3, API, frontend, and SigNoz health before completing deploy | `test_AC8_13_64_*` | `tests/tooling/test_production_infra_smoke.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.65 | Production release reuses successful main CI proof instead of rerunning container-backed tests in the release lane | `test_AC8_13_52_production_release_dry_run_does_not_mutate_production`, `test_AC8_13_9_production_release_runs_prod_safe_e2e_smoke` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.66 | Coveralls uploads strip branch counters so external percentages track the line-only unified coverage gate | `test_AC8_13_66_*` | `tests/tooling/test_build_unified_lcov.py`, `tests/tooling/test_strip_lcov_branches.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.67 | Production release preserves deployed version metadata from image build through Dokploy runtime health | `test_AC8_13_67_production_release_preserves_version_metadata` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.68 | E2E EPIC traceability fails E2E-root test functions missing function-level EPIC IDs or project EPICs without E2E owners | `test_AC8_13_68_*` | `tests/tooling/test_check_e2e_epic_traceability.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.69 | Local test lifecycle binds namespaced infra to ephemeral host ports so parallel branches do not collide | `test_namespaced_infra_uses_ephemeral_host_ports` | `apps/backend/tests/unit/infra/test_test_lifecycle.py` | P0 |
| AC8.13.70 | E2E EPIC traceability fails README EPIC map drift and unclassified E2E-like assets outside declared roots | `test_AC8_13_70_*` | `tests/tooling/test_check_e2e_epic_traceability.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.71 | One lifecycle tool owns PR preview deploy, stop, cleanup, reconciliation, and stable metadata | `test_AC8_13_71_*` | `tests/tooling/test_pr_preview_lifecycle.py` | P0 |
| AC8.13.72 | Dokploy deploy diagnostics redact raw responses and log only allowlisted effective environment diffs | `test_AC8_13_72_*` | `tests/tooling/test_dokploy_redaction.py`, `tests/tooling/test_pr_preview_lifecycle.py` | P0 |
| AC8.13.73 | VPS host hygiene is a Dokploy server schedule that prunes generic Docker and journal garbage while keeping PR preview resources from the last 3 days or the most recent 3 PRs | `test_AC8_13_73_*` | `tests/tooling/test_vps_host_hygiene.py` | P0 |
| AC8.13.74 | Scheduled PR preview cleanup is limited to closed-PR reconciliation and no longer owns generic host hygiene | `test_AC8_13_74_*` | `tests/tooling/test_pr_preview_lifecycle.py`, `tests/tooling/test_vps_host_hygiene.py` | P0 |
| AC8.13.75 | Reporting-only coverage gate summary cannot fail the final CI aggregation job if GitHub Step Summary writes fail | `test_AC8_13_75_coverage_gate_summary_is_nonblocking` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.76 | Playwright mobile UX coverage proves Stage 1 and Stage 2 review workflows avoid document-level horizontal scroll and expose direct completion actions at phone widths | `AC16.26.*` | `apps/frontend/playwright/mobile-ux.spec.ts` | P0 |
| AC8.13.77 | Registry-to-EPIC consistency fails active stub or orphan AC entries instead of silently excluding them | `test_AC8_13_77_*` | `tests/tooling/test_lint_doc_consistency.py` | P0 |
| AC8.13.78 | Mandatory AC traceability requires at least one real proof file that is mapped to a CI-required execution stage | `test_AC8_13_78_*` | `tests/tooling/test_check_ac_traceability.py` | P0 |
| AC8.13.79 | Local E2E command routing distinguishes root deployment E2E from backend Tier-1 API E2E | `test_AC8_13_79_*` | `tests/tooling/test_cli_and_dev_servers.py` | P0 |
| AC8.13.80 | AC coverage analysis supports no-write and stale-report check modes for local verification | `test_AC8_13_80_*` | `tests/tooling/test_analyze_test_ac_coverage.py` | P0 |
| AC8.13.81 | Coverage threshold documentation links to code-owned thresholds instead of copying mutable numeric values | `test_AC8_13_81_*` | `tests/tooling/test_lint_doc_consistency.py` | P1 |
| AC8.13.82 | Playwright responsive UX coverage proves account and review layouts avoid mobile document overflow and desktop local table clipping | `AC2.12.3`, `AC16.27.2`, `AC16.27.3` | `apps/frontend/playwright/mobile-ux.spec.ts` | P0 |
| AC8.13.83 | Personal report package representative fixture contract defines bank cash, income/expense activity, brokerage holdings, manual property valuation, liability, restricted compensation, notes, traceability anchors, and exact Decimal expected outputs | `test_AC8_13_83_representative_package_fixture_contract_defines_exact_outputs` | `tests/tooling/test_personal_report_package_fixture_contract.py` | P0 |
| AC8.13.84 | Personal report package post-merge E2E consumes the representative fixture contract instead of duplicating financial constants or expected totals inline | `test_AC8_13_84_personal_package_e2e_consumes_representative_fixture_contract` | `tests/tooling/test_personal_report_package_fixture_contract.py` | P0 |
| AC8.13.85 | Personal financial report package macro proof is promoted to covered only when the representative fixture contract ACs are part of the critical proof matrix | `test_AC8_13_85_personal_package_macro_proof_is_promoted_after_fixture_contract` | `tests/tooling/test_personal_report_package_fixture_contract.py` | P0 |
| AC8.13.86 | CI fast feedback jobs start after change classification without waiting for behavior-only backend gates | `test_AC8_13_86_*` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.87 | Personal report package fixture contract pins brokerage, dividend, and market-price expected outputs as Decimal-safe audit fixtures | `test_AC8_13_87_personal_package_fixture_pins_brokerage_dividend_and_market_price_outputs` | `tests/tooling/test_personal_report_package_fixture_contract.py` | P0 |
| AC8.13.88 | Personal report package post-merge E2E consumes the audit-grade brokerage, dividend, market-price, and traceability identifier expected outputs | `test_AC8_13_88_personal_package_e2e_consumes_audit_grade_expected_outputs` | `tests/tooling/test_personal_report_package_fixture_contract.py` | P0 |
| AC8.13.89 | PR preview deploy builds and pushes PR-numbered backend/frontend images, then gates E2E on backend and frontend version readiness before browser tests run | `test_AC8_13_89_pr_preview_builds_pr_tagged_images_before_deploy` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |

**Traceability Ownership**:
- This table owns the intended AC-to-proof mapping for EPIC-008.
- Current AC counts, covered/untested totals, and placeholder/stub exclusions are
  owned by `python tools/analyze_test_ac_coverage.py --no-write --stdout` and
  CI traceability artifacts.
- Mandatory AC gate behavior is owned by `python tools/check_ac_traceability.py`.
- Test path execution status for AC proof is owned by
  [test-execution-matrix.yaml](../ssot/test-execution-matrix.yaml).
- Critical product proof-path anchoring is owned by
  `docs/ssot/critical-proof-matrix.yaml` and
  `python tools/check_critical_proof_matrix.py`.
- Do not copy generated AC totals or per-group percentages into this EPIC.

---

## 5. E2E Suite Ownership

Current test counts and coverage percentages belong to generated reports and CI
artifacts, not this EPIC. This section records which suites are allowed to
serve as E2E proof surfaces.

### 5.1 E2E Proof Surface Ownership

E2E file inventories and Tier-1 test-to-AC mappings are generated or validated
by tooling instead of being copied into this EPIC:

| Fact | Owner |
|---|---|
| Test path -> execution stage mapping | [test-execution-matrix.yaml](../ssot/test-execution-matrix.yaml) |
| Product E2E function -> EPIC ownership | `tools/check_e2e_epic_traceability.py` |
| Mandatory AC proof eligibility | `tools/check_ac_traceability.py` |
| Critical macro outcome proof | [critical-proof-matrix.yaml](../ssot/critical-proof-matrix.yaml) |

Product E2E ownership index:

| File | Ownership anchor |
|---|---|
| `apps/backend/tests/e2e/test_auth_flows.py` | Backend auth flow E2E; AC references live in the test file |
| `apps/backend/tests/e2e/test_core_journeys.py` | Backend core journey E2E; AC8.1-AC8.12 references live in the test file |
| `apps/backend/tests/e2e/test_e2e_flows.py` | Backend extended flow E2E; AC references live in the test file |
| `tests/e2e/test_auth_flows.py` | Deployed auth flow E2E; AC references live in the test file |
| `tests/e2e/test_brokerage_upload_to_portfolio_value.py` | Critical proof: AC8.13.10 |
| `tests/e2e/test_core_journeys.py` | Deployed core journey E2E; AC references live in the test file |
| `tests/e2e/test_e2e_flows.py` | Deployed extended flow E2E; AC references live in the test file |
| `tests/e2e/test_four_asset_net_worth_golden_path.py` | Critical proof: AC8.13.42, AC8.13.10, AC5.7.3, AC11.9.1-AC11.9.3, AC17.5.4 |
| `tests/e2e/test_market_data_price_paths.py` | Critical proof: AC11.10.7, AC11.10.11 |
| `tests/e2e/test_personal_financial_report_package.py` | Critical proof: AC5.1.1, AC5.1.4, AC5.2.3, AC5.3.1, AC5.8.1, AC5.12.4, AC5.13.4-AC5.13.5, AC11.8.3, AC11.9.1-AC11.9.3, AC11.11.1-AC11.11.2, AC17.10.1-AC17.10.2, AC8.13.83-AC8.13.85, AC8.13.87-AC8.13.88 |
| `tests/e2e/test_production_readonly_smoke.py` | Production-readonly smoke E2E; AC references live in the test file |
| `tests/e2e/test_statement_full_journey.py` | Critical proof: AC8.13.1-AC8.13.5 |
| `tests/e2e/test_statement_upload_e2e.py` | Statement upload E2E; AC references live in the test file |
| `tests/e2e/test_version_check.py` | Version/runtime E2E; AC references live in the test file |
| `tests/e2e/test_vision_upload_to_dashboard_hard_gate.py` | Critical proof: AC8.13.28-AC8.13.32 |

Product E2E files under `tests/e2e/test_*.py` and
`apps/backend/tests/e2e/test_*.py` must carry AC references directly. They are
not eligible for `docs/analysis/traceability-exceptions.md`; only fixtures and
shared harness files may use that exception path. The `repo/e2e_regressions/`
tree belongs to the `repo/` infra2 submodule and is managed by the infrastructure
submodule sync process.

### 5.3 CI/CD Integration Ownership

Workflow status is not hand-maintained here. CI structure, smoke-test placement,
critical proof checks, and environment isolation are owned by
[ci-cd.md](../ssot/ci-cd.md), `.github/workflows/*.yml`, and the corresponding
tooling tests.

### 5.4 Known Gaps

Known testing gaps are not maintained as detailed status narratives here. Use
these owners instead:

| Gap type | Owner |
|---|---|
| Personal report package proof contract | [critical-proof-matrix.yaml](../ssot/critical-proof-matrix.yaml), #573/#649, `tests/tooling/test_personal_report_package_fixture_contract.py` |
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
- [../ssot/env_smoke_test.md](../ssot/env_smoke_test.md) — environment smoke-test rationale and command semantics.
- [Backend tests README](https://github.com/wangzitian0/finance_report/blob/main/apps/backend/tests/README.md) — backend test-suite navigation.

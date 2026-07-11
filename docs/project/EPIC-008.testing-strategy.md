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
- CI source coverage uses the shared coverage policy in `common/meta/extension/coverage/policy.py`. New backend, frontend, common, and tools modules are expected to appear in the matching LCOV report unless the policy explicitly excludes them.
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

> This group's first row (registration) removed — migrated to the `identity`
> package roadmap as `AC-identity.journeys.1` (migration closeout
> continuation, #1663 / #1706).

> This group's account-CRUD rows (formerly the second through fifth rows)
> removed — migrated to the `ledger` package roadmap as
> `AC-ledger.journeys.1-4` (migration closeout continuation, #1663 / #1707).

### AC8.3: Phase 2 - Manual Journal Entries

> This group's rows removed — migrated to the `ledger` package roadmap as
> `AC-ledger.journeys.5-9` (migration closeout continuation, #1663 / #1707).

### AC8.4: Phase 3 - Statement Import & Parsing

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.4.1 | Statement upload (CSV) | `test_statement_upload_csv()` | `e2e/test_core_journeys.py` | P0 |
| AC8.4.2 | Statement list and get | `test_statement_list_and_get()` | `e2e/test_core_journeys.py` | P0 |
| AC8.4.3 | Statement full flow | `test_statement_full_flow()` | `e2e/test_core_journeys.py` | P0 |

### AC8.5: Phase 4 - Reconciliation Engine

> This group's rows removed — migrated to the `reconciliation` package
> roadmap as `AC-reconciliation.reconciliation-engine.1-3` (migration
> closeout continuation, #1663 / #1711).

### AC8.6: Phase 5 - Reporting & Visualization

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.6.1 | View Balance Sheet | `test_balance_sheet_report()` | `e2e/test_core_journeys.py` | P0 |
| AC8.6.2 | View Income Statement | `test_income_statement_report()` | `e2e/test_core_journeys.py` | P0 |
| AC8.6.3 | View Cash Flow Report | `test_cash_flow_report()` | `e2e/test_core_journeys.py` | P0 |
| AC8.6.4 | Report navigation (all endpoints) | `test_report_navigation_all_endpoints()` | `e2e/test_core_journeys.py` | P1 |

### AC8.7: API Authentication & Authorization

> This group's rows removed — migrated to the `identity` package roadmap as
> `AC-identity.journeys.2`, `.3`, `.4` (migration closeout continuation,
> #1663 / #1706).

### AC8.8: Core E2E Journey Tests

> (AC8.8.1 removed, canonical: migrated to `AC-testing.journeys.1`.)
> (AC8.8.2 removed, canonical: migrated to `AC-testing.journeys.2`.)
> (AC8.8.3 removed, canonical: migrated to `AC-testing.journeys.3`.)
> (AC8.8.4 removed, canonical: migrated to `AC-testing.journeys.4`.)
> (AC8.8.5 removed, canonical: migrated to `AC-testing.journeys.5`.)

### AC8.9: CI/CD Integration Tests

> (AC8.9.1 removed, canonical: migrated to `AC-testing.ci-integration.1`.)
> (AC8.9.2 removed, canonical: migrated to `AC-testing.ci-integration.2`.)
> (AC8.9.3 removed, canonical: migrated to `AC-testing.ci-integration.3`.)
> (AC8.9.4 removed, canonical: migrated to `AC-testing.ci-integration.4`.)

### AC8.10: Must-Have Scenario Traceability

> (AC8.10.1 removed, canonical: migrated to `AC-testing.must-have.1`.)
> (AC8.10.2 removed, canonical: migrated to `AC-testing.must-have.2`.)
> (AC8.10.3 removed, canonical: migrated to `AC-testing.must-have.3`.)
> (AC8.10.4 removed, canonical: migrated to `AC-testing.must-have.4`.)
> (AC8.10.5 removed, canonical: migrated to `AC-testing.must-have.5`.)
> (AC8.10.6 removed, canonical: migrated to `AC-testing.must-have.6`.)
> (AC8.10.7 removed, canonical: migrated to `AC-testing.must-have.7`.)
> (AC8.10.8 removed, canonical: migrated to `AC-testing.must-have.8`.)
> (AC8.10.9 removed, canonical: migrated to `AC-testing.must-have.9`.)

### AC8.11: Phase 2 — Core Financial Journeys

> This group's rows removed — migrated to the `ledger` package roadmap as
> `AC-ledger.journeys.10-14` (migration closeout continuation, #1663 / #1707).

### AC8.12: Provider Error-Path Unit Gates

> **Fully migrated.** The extraction-owned rows (were AC8.12.* rows
> .6/.4/.5) are homed in the `extraction` package roadmap as
> `AC-extraction.812.6` · `AC-extraction.812.4` · `AC-extraction.812.5`
> ([`common/extraction/contract.py`](../../common/extraction/contract.py));
> the remaining rows (were AC8.12.* rows .1/.2/.3) are homed in the `ledger`
> package roadmap as `AC-ledger.fxrevaluation.1-3` (migration closeout
> continuation, #1663 / #1707).

### AC8.13: Tier 3 Browser E2E — Full Statement Journey

> **Partially migrated.** The extraction-owned rows (AC8.13.1 removed, canonical:
> homed in the `extraction` package roadmap as `AC-extraction.813.10` / `.11` /
> `.12` — covering the DBS full-journey browser test, the statement-upload
> full-flow browser test, and the multi-brokerage import test — in
> [`common/extraction/contract.py`](../../common/extraction/contract.py),
> migration closeout wave 3, #1663); the remaining rows below stay with their
> own owners (CI/CD governance tests in `tests/tooling/`, or frontend-only
> Playwright/Vitest specs).

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
> (AC8.13.6 removed, canonical: migrated to `AC-testing.product-gates.1`.)
> (AC8.13.9 removed, canonical: migrated to `AC-testing.deploy-gates.1`.)
> (AC8.13.11 removed, canonical: migrated to `AC-testing.deploy-gates.2`.)
> (AC8.13.12 removed, canonical: migrated to `AC-testing.deploy-gates.3`.)
> (AC8.13.13 removed, canonical: migrated to `AC-testing.deploy-gates.4`.)
> (AC8.13.14 removed, canonical: migrated to `AC-testing.deploy-gates.5`.)
| AC8.13.15 | Unified coverage policy keeps CI source tree, LCOV reports, and Coveralls uploads aligned | `test_*coverage_policy*` / `test_build_unified_lcov*` | `tests/tooling/` | P0 |
> (AC8.13.16 removed, canonical: migrated to `AC-testing.classifier.1`.)
| AC8.13.17 | AC registry generation writes small generated indexes, materializes entries from EPIC docs plus explicit overrides, and preserves no duplicate feature/infra ownership | `test_main_appends_missing_ac_without_rewriting_current_epic_text` / `test_main_materialized_registries_have_no_duplicate_or_missing_ids` / `test_AC8_13_17_ac_traceability_runs_registry_generation_check` | `tests/tooling/test_generate_ac_registry.py` / `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.18 | Brokerage portfolio gate validates market valuation adjustment lines even when unrelated asset lines lower total assets | `test_portfolio_valuation_gate_ignores_unrelated_negative_asset_lines` / `test_portfolio_market_adjustment_survives_unrelated_negative_asset_lines` | `tests/e2e/test_brokerage_upload_to_portfolio_value.py` / `apps/backend/tests/reporting/test_reporting_net_worth_components.py` | P0 |
| AC8.13.19 | Brokerage portfolio gate failures include holdings, valuation adjustment, non-portfolio asset, and balance-sheet diagnostics | `test_portfolio_valuation_gate_failure_diagnostics_are_actionable` | `tests/e2e/test_brokerage_upload_to_portfolio_value.py` | P0 |
> (AC8.13.20 removed, canonical: migrated to `AC-testing.classifier.2`.)
> (AC8.13.21 removed, canonical: migrated to `AC-testing.deploy-gates.6`.)
> (AC8.13.22 removed, canonical: migrated to `AC-testing.deploy-gates.7`.)
> (AC8.13.23 removed, canonical: migrated to `AC-testing.deploy-gates.8`.)
| AC8.13.24 | AC traceability audit is uploaded as a CI artifact instead of failing on a stale committed report | `test_AC8_13_24_ac_traceability_uploads_audit_artifact_without_stale_doc_gate` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.25 | Full CI starts deterministic test and image jobs after change classification while `finish` aggregates lint, AC traceability, tests, image validation, coverage, and skipped-job semantics | `test_AC8_13_25_full_ci_aggregates_static_traceability_and_test_gates` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.26 | CI metrics contract fails when source roots, coverage policy, workflow gates, or AC traceability semantics drift | `test_AC8_13_26_*` | `tests/tooling/` | P0 |
| AC8.13.27 | Pull requests do not publish Coveralls status contexts; main-only Coveralls reporting remains separate from local deterministic coverage gates | `test_AC8_13_27_*` | `tests/tooling/` | P0 |
> (AC8.13.28 removed, canonical: migrated to `AC-testing.product-gates.2`.)
> (AC8.13.29 removed, canonical: migrated to `AC-testing.product-gates.3`.)
> (AC8.13.30 removed, canonical: migrated to `AC-testing.product-gates.4`.)
> (AC8.13.31 removed, canonical: migrated to `AC-testing.product-gates.5`.)
> (AC8.13.32 removed, canonical: migrated to `AC-testing.product-gates.6`.)
| AC8.13.33 | Shared E2E setup caches Python virtualenv and Playwright browser artifacts for staging and preview gates and exports repository-root `PYTHONPATH` for stable `tests.e2e.*` imports | `test_AC8_13_33_e2e_setup_caches_virtualenv_and_playwright_browsers` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.34 | CI and post-merge workflows append queue, execution, and per-job timing summaries to GitHub Step Summary | `test_AC8_13_34_*` | `tests/tooling/` | P1 |
| AC8.13.35 | AC traceability reporting distinguishes real test references from `_ac_stubs` and trivial placeholder assertions | `test_classifies_placeholder_assertion`, `test_classifies_pure_pass_ac_file_as_placeholder`, `test_classifies_ac_stub_directory`, `test_placeholder_and_stub_refs_do_not_count_as_real_coverage` | `tests/tooling/test_check_ac_traceability.py` | P0 |
> (AC8.13.36 removed, canonical: migrated to `AC-testing.deploy-gates.9`.)
| AC8.13.37 | AC traceability fails mandatory ACs that are covered only by `_ac_stubs` | `test_returns_one_with_stub_only` | `tests/tooling/test_check_ac_traceability.py` | P0 |
> (AC8.13.38 removed, canonical: migrated to `AC-testing.preview.1`.)
| AC8.13.39 | Runtime and container versions stay aligned across local, CI, and Docker environments | `test_AC8_13_39_*` | `tests/tooling/test_toolchain_contract.py` | P0 |
> (AC8.13.40 removed, canonical: migrated to `AC-testing.deploy-gates.10`.)
| AC8.13.41 | Critical proof matrix fails when a core product proof path is backed only by broad or reference-only AC strings | `test_*critical_proof_matrix*` | `tests/tooling/test_check_critical_proof_matrix.py` | P0 |
> (AC8.13.42 removed, canonical: migrated to `AC-testing.product-gates.7`.)
| AC8.13.44 | Local bootstrap provides one command for runtimes, dependency setup, pre-commit hooks, and container-runtime diagnostics | `test_AC8_13_44_*` | `tests/tooling/test_bootstrap_local.py`, `tests/tooling/test_cli_and_dev_servers.py`, `tests/tooling/test_toolchain_contract.py` | P0 |
| AC8.13.45 | Local verification entry points fail on the same backend format errors and route `make test` through the root Moon test command without hashing the infra submodule gitlink as a file input | `test_AC8_13_45_*` | `tests/tooling/test_cli_and_dev_servers.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
> (AC8.13.46 removed, canonical: migrated to `AC-testing.preview.2`.)
| AC8.13.47 | Remaining delivery-engine optimizations are captured in a tracked project recommendation note | `test_AC8_13_47_delivery_engine_recommendations_are_tracked` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.48 | Frontend gap tests cover route, component, and API helper paths so frontend LCOV line coverage reaches 99% | `test_AC8_13_48_*` | `apps/frontend/src/__tests__/stage2ReviewQueueCoverage99.test.tsx`, `apps/frontend/src/__tests__/statementReviewPage.coverage.test.tsx`, `apps/frontend/src/__tests__/statementDetailPage.coverage.test.tsx`, `apps/frontend/src/__tests__/StatementUploader.test.tsx`, `apps/frontend/src/__tests__/journalPage.test.tsx`, `apps/frontend/src/__tests__/reconciliationWorkbenchComponent.test.tsx`, `apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx`, `apps/frontend/src/__tests__/apiFunctions.test.ts`, `apps/frontend/src/__tests__/accountsPage.test.tsx`, `apps/frontend/src/__tests__/assetsPage.test.tsx`, `apps/frontend/src/__tests__/statementsPage.test.tsx`, `apps/frontend/src/__tests__/useWorkspaceHook.test.tsx`, `apps/frontend/src/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx`, `apps/frontend/src/__tests__/uiGapAudit.netWorthTimeSeries.test.tsx`, `apps/frontend/src/__tests__/uiGapAudit.processingVisibility.test.tsx` | P0 |
> (AC8.13.49 removed, canonical: migrated to `AC-testing.deploy-gates.11`.)
| AC8.13.50 | Critical proof matrix validates the closed macro outcome set from README through owner EPICs and E2E proof anchors | `test_AC8_13_50_*` | `tests/tooling/test_check_critical_proof_matrix.py` | P0 |
> (AC8.13.51 removed, canonical: migrated to `AC-testing.deploy-gates.12`.)
> (AC8.13.52 removed, canonical: migrated to `AC-testing.deploy-gates.13`.)
| AC8.13.53 | Common owns SSOT, config and CI contracts, coverage policy, and isolation helpers; command entry points and tool-owned implementations live in `tools/`; PR CI avoids optional Moon bootstrap for heavy gates that run direct `pytest` or `npm` commands, with Moon availability covered as static config contracts | `test_AC8_13_53_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_ci_metrics_contract.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.54 | Critical proof matrix fails when README macro outcomes, matrix outcomes, or owner EPIC reverse declarations drift | `test_AC8_13_54_*` | `tests/tooling/test_check_critical_proof_matrix.py` | P0 |
> (AC8.13.55 removed, canonical: migrated to `AC-testing.deploy-gates.14`.)
| AC8.13.56 | Coverage command entry points run from `tools/`; the shared policy stays in `common/meta/extension/coverage/policy.py`, and command implementations live under `tools/_lib/coverage/` | `test_AC8_13_56_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_ci_metrics_contract.py`, `tests/tooling/test_coverage_policy.py`, `tests/tooling/test_build_unified_lcov.py` | P0 |
| AC8.13.57 | SSOT and AC command entry points run from `tools/` while shared implementations live in the packages that own them (`common/testing/`, `common/meta/extension/`, `common/platform/`); the residual `common/ssot/` generator escape hatch is retired | `test_AC8_13_57_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_ci_metrics_contract.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.58 | CI and toolchain command entry points run from `tools/`; reusable contracts live in the packages that own them (`common/runtime/`, `common/testing/`, `common/meta/extension/`), while report and shell command implementations live under `tools/_lib/` | `test_AC8_13_58_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_toolchain_contract.py`, `tests/tooling/test_ci_change_classifier.py`, `tests/tooling/test_github_workflow_timing_summary.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.59 | Config validation command entry points run from `tools/` while shared implementations live under `apps/backend/src/runtime/extension/` (moved from `common/config/` when that package folded into `runtime`, #1669) | `test_AC8_13_59_*` | `tests/tooling/test_common_tooling_modules.py`, `tests/tooling/test_check_env_keys.py`, `tests/tooling/test_validate_schemas.py` | P0 |
> (AC8.13.60 removed, canonical: migrated to `AC-testing.deploy-gates.15`.)
| AC8.13.61 | Visual regression residual is explicitly owned by EPIC-008 as a P3 future testing capability | `test_AC8_13_61_visual_regression_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P3 |
| AC8.13.62 | Test observability residuals are explicitly owned by EPIC-008 with current replacements and future dashboard/notification/trend scope | `test_AC8_13_62_test_observability_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P2 |
| AC8.13.63 | Performance testing residual is explicitly owned by EPIC-008 with current Locust/staging coverage and future P95 trend gate scope | `test_AC8_13_63_performance_testing_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P2 |
> (AC8.13.64 removed, canonical: migrated to `AC-testing.deploy-gates.16`.)
> (AC8.13.65 removed, canonical: migrated to `AC-testing.deploy-gates.17`.)
| AC8.13.66 | Coveralls uploads strip branch counters so external percentages track the line-only unified coverage gate | `test_AC8_13_66_*` | `tests/tooling/test_build_unified_lcov.py`, `tests/tooling/test_strip_lcov_branches.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
> (AC8.13.67 removed, canonical: migrated to `AC-testing.deploy-gates.18`.)
| AC8.13.68 | E2E EPIC traceability fails E2E-root test functions missing function-level EPIC IDs or project EPICs without E2E owners | `test_AC8_13_68_*` | `tests/tooling/test_check_e2e_epic_traceability.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.69 | Local test lifecycle binds namespaced infra to ephemeral host ports so parallel branches do not collide | `test_namespaced_infra_uses_ephemeral_host_ports` | `apps/backend/tests/unit/infra/test_test_lifecycle.py` | P0 |
| AC8.13.70 | E2E EPIC traceability fails README EPIC map drift and unclassified E2E-like assets outside declared roots | `test_AC8_13_70_*` | `tests/tooling/test_check_e2e_epic_traceability.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
> (AC8.13.71 removed, canonical: migrated to `AC-testing.preview.3`.)
> (AC8.13.72 removed, canonical: migrated to `AC-testing.preview.4`.)
> (AC8.13.73 removed, canonical: migrated to `AC-testing.preview.5`.)
> (AC8.13.74 removed, canonical: migrated to `AC-testing.preview.6`.)
| AC8.13.75 | Reporting-only coverage gate summary cannot fail the final CI aggregation job if GitHub Step Summary writes fail | `test_AC8_13_75_coverage_gate_summary_is_nonblocking` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.76 | Playwright mobile UX coverage proves Stage 1 and Stage 2 review workflows avoid document-level horizontal scroll and expose direct completion actions at phone widths | `AC16.26.*` | `apps/frontend/playwright/mobile-ux.spec.ts` | P0 |
| AC8.13.77 | Registry-to-EPIC consistency fails active stub or orphan AC entries instead of silently excluding them | `test_AC8_13_77_*` | `tests/tooling/test_lint_doc_consistency.py` | P0 |
| AC8.13.78 | Mandatory AC traceability requires at least one real proof file that is mapped to a CI-required execution stage | `test_AC8_13_78_*` | `tests/tooling/test_check_ac_traceability.py` | P0 |
| AC8.13.79 | Local E2E command routing distinguishes root deployment E2E from backend Tier-1 API E2E | `test_AC8_13_79_*` | `tests/tooling/test_cli_and_dev_servers.py` | P0 |
| AC8.13.80 | AC coverage analysis supports no-write and stale-report check modes for local verification | `test_AC8_13_80_*` | `tests/tooling/test_analyze_test_ac_coverage.py` | P0 |
| AC8.13.81 | Coverage threshold documentation links to code-owned thresholds instead of copying mutable numeric values | `test_AC8_13_81_*` | `tests/tooling/test_lint_doc_consistency.py` | P1 |
| AC8.13.82 | Playwright responsive UX coverage proves account and review layouts avoid mobile document overflow and desktop local table clipping | `AC2.17.1`, `AC16.27.2`, `AC16.27.3` | `apps/frontend/playwright/mobile-ux.spec.ts` | P0 |
> (AC8.13.83 removed, canonical: migrated to `AC-testing.product-gates.8`.)
> (AC8.13.84 removed, canonical: migrated to `AC-testing.product-gates.9`.)
> (AC8.13.85 removed, canonical: migrated to `AC-testing.product-gates.10`.)
| AC8.13.86 | CI fast feedback jobs start after change classification without waiting for behavior-only backend gates | `test_AC8_13_86_*` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
> (AC8.13.87 removed, canonical: migrated to `AC-testing.product-gates.11`.)
> (AC8.13.88 removed, canonical: migrated to `AC-testing.product-gates.12`.)
> (AC8.13.89 removed, canonical: migrated to `AC-testing.preview.7`.)
| AC8.13.90 | Frontend exposes `/frontend-version.json` with deployed `git_sha`/`version` metadata for PR preview readiness checks | `AC8.13.90 returns deployed frontend version metadata for PR preview readiness` | `frontendVersionRoute.test.ts` | P0 |
| AC8.13.92 | Frontend Vitest coverage keeps a code-owned 98% baseline for line, statement, and function metrics plus an explicit branch floor while representative low-coverage routes and workflow surfaces stay covered | `AC8.13.92*` | `apps/frontend/src/__tests__/coverageBaseline.test.ts`, `apps/frontend/src/__tests__/personalReportPackagePage.test.tsx`, `apps/frontend/src/__tests__/workflowSurfaces.test.tsx`, `apps/frontend/src/__tests__/chatPanelComponent.test.tsx`, `apps/frontend/src/__tests__/investmentPerformanceSchedule.test.tsx`, `apps/frontend/src/__tests__/journalPage.test.tsx`, `apps/frontend/src/__tests__/sankeyChartComponent.test.tsx`, `apps/frontend/src/__tests__/toastProviderComponent.test.tsx`, `apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx` | P0 |
> (AC8.13.93 removed, canonical: migrated to `AC-testing.deploy-gates.19`.)
| AC8.13.94 | CI/CD documentation separates environment taxonomy from pipeline stages and declares the sparse env x stage execution matrix | `test_AC8_13_94_env_and_pipeline_stage_contract_is_documented` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC8.13.95 | Local verification guidance defaults to affected fast tests and defines risk-triggered escalation for high-impact paths | `test_AC8_13_95_local_fast_gate_and_escalation_policy_are_documented` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
> (AC8.13.96 removed, canonical: migrated to `AC-testing.classifier.3`.)
> (AC8.13.97 removed, canonical: migrated to `AC-testing.classifier.4`.)
> (AC8.13.98 removed, canonical: migrated to `AC-testing.preview.8`.)
| AC8.13.99 | Frontend local and CI gates run full TypeScript checking, including tests, instead of relying only on Next production build type checks | `test_AC8_13_99_frontend_typecheck_is_a_required_gate` | `tests/tooling/test_frontend_typecheck_contract.py` | P0 |
> (AC8.13.100 removed, canonical: migrated to `AC-testing.preview.9`.)
> (AC8.13.101 removed, canonical: migrated to `AC-testing.preview.10`.)
> (AC8.13.102 removed, canonical: migrated to `AC-testing.preview.11`.)
> (AC8.13.103 removed, canonical: migrated to `AC-testing.deploy-gates.20`.)
> (AC8.13.104 removed, canonical: migrated to `AC-testing.classifier.5`.)
> (AC8.13.105 removed, canonical: migrated to `AC-testing.deploy-gates.21`.)
> (AC8.13.107 removed, canonical: migrated to `AC-testing.preview.12`.)
> (AC8.13.108 removed, canonical: migrated to `AC-testing.deploy-gates.22`.)
> (AC8.13.109 removed, canonical: migrated to `AC-testing.deploy-gates.23`.)
> (AC8.13.110 removed, canonical: migrated to `AC-testing.classifier.6`.)
> (AC8.13.111 removed, canonical: migrated to `AC-testing.classifier.7`.)
> (AC8.13.112 removed, canonical: migrated to `AC-testing.classifier.8`.)
> (AC8.13.113 removed, canonical: migrated to `AC-testing.deploy-gates.24`.)
> (AC8.13.114 removed, canonical: migrated to `AC-testing.preview.13`.)
> (AC8.13.115 removed, canonical: migrated to `AC-testing.preview.14`.)
> (AC8.13.116 removed, canonical: migrated to `AC-testing.deploy-gates.25`.)
| AC8.13.118 | Critical-path timeouts and retries are documented in `docs/ssot/ci-cd.md` | `test_AC8_13_118_timeouts_and_retries_documented` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
> (AC8.13.119 removed, canonical: migrated to `AC-testing.deploy-gates.26`.)
> (AC8.13.120 removed, canonical: migrated to `AC-testing.deploy-gates.27`.)
| AC8.13.121 | PR CI runs a schema migration contract against ephemeral Postgres with `alembic upgrade head`, `alembic check`, uploaded context, and `finish` aggregation | `test_AC8_13_121_pr_ci_runs_schema_migration_contract` | `tests/tooling/test_schema_quality_contract.py` | P0 |
| AC8.13.122 | Backend schema drift guard no longer treats an out-of-date Alembic target or missing CLI as success; PR CI `schema-migrations` owns hard proof | `test_AC8_13_122_schema_drift_guard_does_not_accept_outdated_targets` | `tests/tooling/test_schema_quality_contract.py` | P0 |
| AC8.13.123 | Schema guardrails scan the real `apps/backend/migrations/versions` directory instead of a test-local path | `test_AC8_13_123_schema_guardrails_scan_real_migration_directory` | `tests/tooling/test_schema_quality_contract.py` | P0 |
| AC8.13.124 | AC traceability gate and uploaded audit builder consume the same SSOT test-surface definition, including frontend Playwright tests | `test_AC8_13_124_traceability_gate_and_audit_builder_share_test_surface` | `tests/tooling/test_schema_quality_contract.py` | P1 |
> (AC8.13.125 removed, canonical: migrated to `AC-testing.preview.15`.)
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
> (AC8.13.137 removed, canonical: migrated to `AC-testing.deploy-gates.28`.)
| AC8.13.138 | The AC-score ratchet baseline is a PERSISTED ratchet stored conflict-free as sorted, one-AC-per-line JSONL with a `merge=union` gitattribute, loading into the same in-memory shape the ratchet uses — and the ratchet still fails on regression, missing evidence, or non-pass code (the derived aggregate views it once sat beside are now covered by AC8.13.139) | `test_AC8_13_138_baseline_is_sorted_jsonl_with_union_merge`, `test_AC8_13_138_baseline_loads_to_legacy_shape`, `test_AC8_13_138_ratchet_still_fails_on_regression_and_missing_ac` | `tests/tooling/test_proof_index_architecture.py` | P1 |
| AC8.13.139 | The cross-cutting proof/vision/status indexes are unified onto ONE AC-keyed graph (`common/testing/ac_graph.py`) built from sharded sources (EPIC docs, `@ac_proof` decorators, `vision.md`, `critical-proof-outcomes.yaml`, the JSONL ratchet); the critical-proof matrix, vision-proof matrix, and README EPIC-status table are DERIVED on demand and never committed-materialized; and `tools/check_ac_index.py` is exactly TWO gates — **Gate A INTEGRITY** (`check_integrity`, hard: every AC is managed/enumerated with a protection record AND no dangling reference — every `@ac_proof` resolves to a real test + real AC, every vision item with an owner EPIC backs an AC, every macro outcome's proof_ids resolve, every mandatory active AC has a real test reference, with the per-edge-type messages preserved verbatim) and **Gate B PROTECTION RATCHET** (see AC8.13.140) — instead of N byte-compares | `test_AC8_13_139_gate_passes_on_consistent_tree`, `test_AC8_13_139_gate_fails_on_dangling_vision_item`, `test_AC8_13_139_gate_fails_on_proof_missing_test_or_ac`, `test_AC8_13_139_gate_fails_on_mandatory_ac_without_proof`, `test_AC8_13_139_gate_fails_on_macro_outcome_missing_proof`, `test_AC8_13_139_gate_fails_on_ratchet_regression`, `test_AC8_13_139_no_committed_materialized_index_files` | `tests/tooling/test_ac_index_consistency.py` | P1 |
| AC8.13.140 | Gate B (PROTECTION RATCHET) of `tools/check_ac_index.py` is monotonic, per-type and conflict-safe: an AC with an all-empty protection record is still "managed" (managed = present in the structure, not that it has any test); part 1 is the per-AC behavioural-score floor (`ac-score-baseline.jsonl`, `merge=union`, unchanged); part 2 is a per-type COUNT floor (`docs/ssot/protection-floor.json`) where the current count of mandatory active ACs at each type (`has_real_ref`, `has_proof`, `has_score`, `has_mirror`) must be `>=` the committed floor — adding protection only RAISES the current count and passes without editing the floor file, the default all-zero/missing floor is valid, and floors are raised only by the explicit `--update-floor` action so protection-adding PRs never touch the file | `test_AC8_13_140_every_ac_managed_with_empty_protection_passes`, `test_AC8_13_140_count_floor_default_empty_passes`, `test_AC8_13_140_count_floor_fails_when_type_drops_below_floor`, `test_AC8_13_140_count_floor_passes_when_protection_added`, `test_AC8_13_140_update_floor_raises_floors`, `test_AC8_13_140_load_floor_rejects_malformed_value`, `test_AC8_13_140_write_floor_creates_missing_parent` | `tests/tooling/test_ac_index_consistency.py` | P1 |
| AC8.13.141 | The AC-index gate is OPERATIONALLY exactly TWO CI gates: the former standalone CI-stage traceability contract (`common.testing.check_ac_traceability.run_traceability`: a mandatory active AC must resolve to a real test reference in a CI-REQUIRED execution stage per `docs/ssot/test-execution-matrix.yaml`, with the placeholder-only/stub-only/unexecuted-only/missing classifications) and critical-proof contract (`common.testing.check_critical_proof_matrix.validate_matrix_contract`: per-proof trust_mode/mirror/required_markers/scope/ci_tier + manual_gate evidence + macro-outcome shape contract) gate STEPS are RETIRED as separate CI steps; their logic is FOLDED into `check_ac_index`'s Gate A INTEGRITY (`check_repo_contracts`) by importing those modules as LIBRARIES (no reimplementation, verbatim messages), so every failure they caught still fails the single gate, the index gate runs ONCE (lint job, not duplicated in `ac-traceability`), and no CI job name / required status context is renamed | `test_AC8_13_141_green_tree_old_gates_and_consolidated_agree`, `test_AC8_13_141_unexecuted_only_is_caught`, `test_AC8_13_141_placeholder_only_is_caught`, `test_AC8_13_141_stub_only_is_caught`, `test_AC8_13_141_missing_is_caught`, `test_AC8_13_141_critical_proof_invalid_trust_mode_caught`, `test_AC8_13_141_critical_proof_llm_missing_mirror_caught`, `test_AC8_13_141_critical_proof_missing_marker_caught`, `test_AC8_13_141_critical_proof_manual_gate_without_evidence_caught`, `test_AC8_13_141_consolidated_gate_surfaces_critical_proof_errors`, `test_AC8_13_141_old_standalone_gate_steps_removed_from_ci`, `test_AC8_13_141_single_ac_index_gate_runs_exactly_once_per_required_path`, `test_AC8_13_141_ci_job_names_and_required_contexts_unchanged` | `tests/tooling/test_two_gate_consolidation.py` | P1 |
| AC8.13.142 | CI simplification keeps a transitional gate inventory where every workflow job has exactly one proof `stage` and one `task_category`; the inventory matches live workflow jobs and `finish.needs`, rejects legacy `category` keys, and records resolved duplicate cleanups so cleanup PRs do not leave both old and new entrances behind {tier:CODE-ONLY} {proof:property} | `test_AC8_13_142_ci_gate_inventory_uses_stage_and_task_category_per_job`, `test_AC8_13_142_finish_inventory_matches_ci_fan_in`, `test_AC8_13_142_duplicate_cleanup_is_explicit_not_implicit` | `tests/tooling/test_ci_gate_inventory.py` | P1 |
| AC8.13.143 | Main CI automatically opens or updates a reviewed baseline PR when `unified-coverage.json` rises, while PR CI keeps the committed no-regression gate and no new required status context is introduced | `test_AC8_13_143_unified_coverage_updates_baseline_through_pr_not_direct_main_push` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
> (AC8.13.144 removed, canonical: migrated to `AC-testing.deploy-gates.29`.)
| AC8.13.145 | Backend Tier-1 API E2E keeps PR fail-fast for speed but push/main runs the full Tier-1 suite so the JUnit artifact reports every failing API journey in one run | `test_AC8_13_145_backend_tier1_pr_fail_fast_but_main_reports_all_failures` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
> (AC8.13.146 removed, canonical: migrated to `AC-testing.deploy-gates.30`.)
| AC8.13.147 | Frontend PR CI is split into build/typecheck, Vitest coverage, provider-free Playwright, and telemetry E2E jobs while preserving `coverage-frontend`, frontend Vitest JUnit evidence, `unified-coverage` fan-in, AC behavioral ratchet fan-in, and `finish` aggregation over every frontend gate | `test_AC8_13_147_frontend_ci_split_preserves_merge_authority` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.148 | Backend fast-test CI shards rebalance the current critical path with a 5-way `pytest-split` matrix, a committed duration seed, least-duration assignment, and a seed-size guard so CI cannot silently fall back to unseeded even splitting | `test_AC8_13_148_backend_shards_use_seeded_5_way_split` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.149 | CI fan-in jobs trim post-backend tail work without weakening merge authority: unified coverage runs stdlib Python over scoped coverage artifacts, and the AC behavioral ratchet downloads only JUnit-producing test-context artifacts | `test_AC8_13_149_fan_in_jobs_download_only_required_artifacts` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.150 | AC is the only coverage key for CI proof placement: `@ac_proof` remains backward compatible while each proof edge can carry execution metadata as `proof(name, stage, task_category)`, where `stage` and `task_category` are proof attributes rather than identity keys and remain separate from authority tier / `proof_kind` {tier:CODE-ONLY} {proof:property} | `test_AC8_13_150_ac_proof_execution_model_is_ac_keyed_and_backward_compatible` | `tests/tooling/test_ac_proof_execution_model.py` | P1 |
| AC8.13.151 | CI gate inventory vocabulary is shared with the AC proof execution helper: top-level `stages` and `task_categories` match `common.testing.ac_proof_execution` exactly, so docs, runtime proof metadata, and inventory contracts cannot drift independently {tier:CODE-ONLY} {proof:property} | `test_AC8_13_151_ci_gate_inventory_uses_shared_proof_execution_vocabulary` | `tests/tooling/test_ci_gate_inventory.py` | P1 |
> (AC8.13.152 removed, canonical: migrated to `AC-testing.classifier.9`.)
| AC8.13.153 | The staging AI/OCR corpus gate body lives once in a reusable `staging-ai-ocr-gate.yml` (`workflow_call`) consumed by both the inline staging deploy chain and the manual `staging-ai-ocr-gate` dispatch; the two entrances are `uses:` callers that differ only by a `blocking` input (record-only vs fail-fast) plus checkout/expected_sha, the duplicated job body is removed, and the cleanup is recorded in the gate inventory {tier:CODE-ONLY} {proof:property} | `test_AC8_13_153_staging_ai_ocr_gate_is_a_single_reusable_workflow` | `tests/tooling/test_ci_gate_inventory.py` | P1 |
| AC8.13.154 | The production release line (`dry-run`, `deploy`) is split out of `deploy.yml` into a manual-dispatch-only `release.yml` with a `production-release-<version_ref>` concurrency group (`cancel-in-progress: false`) so two prod releases never run concurrently; `deploy.yml` keeps staging deploy and tag-push promote, and the workflow contract plus gate inventory track the new file and re-homed job ids {tier:CODE-ONLY} {proof:property} | `test_AC8_13_154_production_release_line_lives_in_release_yml` | `tests/tooling/test_ci_gate_inventory.py` | P1 |
| AC8.13.155 | The former app-side reclaim split is retired: `preview.yml#cleanup` now dispatches a `preview-teardown` signal to infra2 (which owns the 1:1 reclaim via `preview-teardown.yml` + the hourly `preview-leak-check` fallback), and `maintenance.yml#cleanup` is GHCR-image-pruning only; the `pr_preview_cleanup_event_vs_scheduled` inventory entry records this `retired` state, not a `keep_separate` reclaim split {tier:CODE-ONLY} {proof:property} | `test_AC8_13_155_pr_preview_reclaim_is_dispatched_to_infra2` | `tests/tooling/test_ci_gate_inventory.py` | P1 |
> (AC8.13.156 removed, canonical: migrated to `AC-testing.deploy-gates.31`.)
> (AC8.13.157 removed, canonical: migrated to `AC-testing.deploy-gates.32`.)
> (AC8.13.158 removed, canonical: migrated to `AC-testing.deploy-gates.33`.)
> (AC8.13.159 removed, canonical: migrated to `AC-testing.deploy-gates.34`.)
> (AC8.13.160 removed, canonical: migrated to `AC-testing.deploy-gates.35`.)
> (AC8.13.161 removed, canonical: migrated to `AC-testing.classifier.10`.)
| AC8.13.162 | `frontend-telemetry-e2e` is right-moved off PRs that touch no `apps/frontend/**` path (mirrors `container-images`' `image_build_required` pattern): it always runs on a main/release push or manual dispatch, and a skip is a pass (not a gap) in `finish`'s aggregation, so unrelated PRs stop paying its browser-install wall-clock cost (#1689) {tier:CODE-ONLY} {proof:property} | `test_AC8_13_162_frontend_telemetry_e2e_is_right_moved_and_skip_is_a_pass` | `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
| AC8.13.163 | `calculate_unified_coverage`'s no-regression gate accepts a `--gate-components`/`COVERAGE_GATE_COMPONENTS` scope: on `pull_request` events it BLOCKS only on regressions in the components the PR actually changed (an unrelated component's regression, and the blended "unified" total, are still computed and reported but do not fail the job); every component is still merged into `unified-coverage.json` regardless of scope, and a `push` to `main` always omits the scope (full, unscoped, unchanged-strict gate) (#1689) {tier:CODE-ONLY} {proof:property} | `test_AC8_13_163_scoped_to_the_regressed_component_still_fails` | `tests/tooling/test_coverage_artifact_preflight.py` | P1 |
| AC8.13.164 | `common.testing.evidence_bundle.build_evidence_bundle` assembles ONE evidence bundle (a gate map of lane->job->blocking, the four raise-only ratchet water-lines [unified coverage, AC behavioural score, AC authority-tier debt, protection floor], and corpus per-field accuracy from the cassette graded-eval corpus) from already-computed CI artifacts — it never re-runs a gate to get its data — with an optional `provider_health` field populated only by callers with a provider-backed gate result (#1690) {tier:CODE-ONLY} {proof:property} | `test_AC8_13_164_bundle_assembles_the_four_ratchet_water_lines_and_gate_map` | `tests/tooling/test_evidence_bundle.py` | P1 |
| AC8.13.165 | Main-branch CI (after `unified-coverage` + `ac-behavioral-ratchet` complete) and the nightly `audit-replay.yml` run both generate the evidence bundle via the same `tools/generate_evidence_bundle.py` CLI, writing it to `$GITHUB_STEP_SUMMARY` and uploading it as a named `evidence-bundle` artifact; the nightly producer additionally supplies `--provider-status`/`--provider-exit-code` from the staging AI/OCR gate's own `ai_ocr_status`/`ai_ocr_exit_code` outputs, the main-CI producer does not (#1690) {tier:CODE-ONLY} {proof:property} | `test_AC8_13_165_both_producers_wire_the_same_generator_into_their_workflow` | `tests/tooling/test_evidence_bundle.py` | P1 |

### AC8.14: Product Trust Proof Mirrors

> (AC8.14.1 removed, canonical: migrated to `AC-testing.trust-mirrors.1`.)
> (AC8.14.2 removed, canonical: migrated to `AC-testing.trust-mirrors.2`.)
> (AC8.14.3 removed, canonical: migrated to `AC-testing.trust-mirrors.3`.)
> (AC8.14.4 removed, canonical: migrated to `AC-testing.trust-mirrors.4`.)

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

> (AC8.17.1 removed, canonical: migrated to `AC-identity.purge.1`.)
> (AC8.17.2 removed, canonical: migrated to `AC-identity.purge.2`.)
> (AC8.17.3 removed, canonical: migrated to `AC-identity.purge.3`.)
> (AC8.17.4 removed, canonical: migrated to `AC-identity.purge.4`.)
> (AC8.17.5 removed, canonical: migrated to `AC-identity.purge.5`.)
>
> The purge library moved from `src/services/test_account_purge.py` into the
> `identity` package (`src/identity/extension/account_purge.py`, #1677 —
> purging user accounts and their owned rows is user-lifecycle
> administration), so its ACs live in
> [`common/identity/contract.py`](../../common/identity/contract.py)'s
> `roadmap` (migration closeout wave 3, #1663). Its tests moved to
> `apps/backend/tests/identity/test_account_purge.py`.

The operator entry point is `tools/purge_test_accounts.py` (dry-run by default;
`--apply` to delete; runbook in `docs/contributing/staging-test-account-cleanup.md`).

---

### AC8.18: Tier 2 Deployed HTTP E2E Proof Semantics

Tier 2 is the lightweight deployed-HTTP lane between Tier 1 in-process API E2E
and Tier 3 browser/provider-heavy E2E. It proves the deployed URL, routing,
version, public API reachability, frontend reachability, and unauthenticated
protection boundary through real HTTP. It is not a line-coverage input and a
not-run/env-gated advisory report is never proof eligible.

> (AC8.18.1 removed, canonical: migrated to `AC-testing.tier2.1`.)
> (AC8.18.2 removed, canonical: migrated to `AC-testing.tier2.2`.)
> (AC8.18.3 removed, canonical: migrated to `AC-testing.tier2.3`.)

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

> This group's second row removed — migrated to the `identity` package
> roadmap as `AC-identity.journeys.5` (migration closeout continuation,
> #1663 / #1706).

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

> (AC8.20.1 removed, canonical: migrated to `AC-testing.review-threads.1`.)
> (AC8.20.2 removed, canonical: migrated to `AC-testing.review-threads.2`.)
> (AC8.20.3 removed, canonical: migrated to `AC-testing.review-threads.3`.)

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

> (AC8.21.1 removed, canonical: migrated to `AC-testing.seeded-journey.1`.)
> (AC8.21.2 removed, canonical: migrated to `AC-testing.seeded-journey.2`.)
> (AC8.21.3 removed, canonical: migrated to `AC-testing.seeded-journey.3`.)

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

> (AC8.22.1 removed, canonical: migrated to `AC-testing.matrix.1`.)
> (AC8.22.2 removed, canonical: migrated to `AC-testing.matrix.2`.)
> (AC8.22.3 removed, canonical: migrated to `AC-testing.matrix.3`.)
> (AC8.22.4 removed, canonical: migrated to `AC-testing.matrix.4`.)
> (AC8.22.5 removed, canonical: migrated to `AC-testing.matrix.5`.)
> (AC8.22.6 removed, canonical: migrated to `AC-testing.matrix.6`.)

### AC8.23: Workflow Selection Conformance & Execution Reconciliation

Follow-up to AC8.22 (issue #1557): marker expressions and test paths for every
junit-emitting pytest invocation across `.github/workflows/*.yml` now live once
in `common/testing/matrix.py` (`WORKFLOW_PYTEST_CONTRACTS`), enforced
fail-closed by a central conformance gate; and a declared `ci_tier="pr_ci"` on
an `@ac_proof` is reconciled against actual PR junit evidence in the
`ac-behavioral-ratchet` job — execution tier becomes a contract, not metadata.

> (AC8.23.1 removed, canonical: migrated to `AC-testing.conformance.1`.)
> (AC8.23.2 removed, canonical: migrated to `AC-testing.conformance.2`.)
> (AC8.23.3 removed, canonical: migrated to `AC-testing.conformance.3`.)
> (AC8.23.4 removed, canonical: migrated to `AC-testing.conformance.4`.)

### AC8.24: Package Test Declarations, Environment Preconditions & Mirror Ratchet

Series closer (issue #1558): domain packages declare the test roots they own
in their own `contract.py` (`TEST_ROOTS`), aggregated into the generated
execution-matrix view; E2E stages carry an explicit environment precondition
(runtime's smoke gate) that runs before any test so a red environment is never
attributed as a test failure; and the mirror-assertion stock is locked behind
an only-goes-down ratchet (`common/testing/mirror_ratchet.py`), stopping the
#1435 accretion.

> (AC8.24.1 removed, canonical: migrated to `AC-testing.declarations.1`.)
> (AC8.24.2 removed, canonical: migrated to `AC-testing.declarations.2`.)
> (AC8.24.3 removed, canonical: migrated to `AC-testing.declarations.3`.)

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

> This group's rows removed — migrated to the `runtime` package roadmap as
> `AC-runtime.23.1-2` (migration closeout continuation, #1663 / #1714).

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
| `apps/backend/tests/e2e/test_core_journeys.py` | Backend core journey E2E; AC8.1-AC8.12 references live in the test file |
| `tests/e2e/test_epic022_ia_shell.py` | EPIC-022 everyday-user IA shell product owner E2E (in-runner preview lane); AC22.1 references live in the test file |
| `tests/e2e/test_institution_statement_journeys.py` | Per-institution live-extraction staging journeys (audit-replay corpus, #1613); ACs live in the `llm` package roadmap (AC-llm.12.1 AC-llm.12.2 AC-llm.12.3 AC-llm.12.4, `common/llm/contract.py`) |
| `apps/backend/tests/e2e/test_epic025_dry_ssot_e2e.py` | EPIC-025 DRY/SSOT product owner E2E; `AC-reporting.dry-ssot.1` (reporting_calc extraction is behavior-preserving, `common/reporting/contract.py`) references live in the test file |
| `apps/backend/tests/e2e/test_statement_corpus_journeys.py` | Extraction-corpus merge-tier E2E; ACs live in the `llm` package roadmap (AC-llm.11.1 AC-llm.11.2 AC-llm.11.3 AC-llm.11.4 AC-llm.11.5 AC-llm.11.6, `common/llm/contract.py`) |
| `apps/backend/tests/e2e/test_seeded_statement_journey.py` | Seeded no-LLM statement journey (provider-free merge tier); ACs live in the `testing` package roadmap (AC-testing.seeded-journey.1-3, `common/testing/contract.py`) |
| `tests/e2e/test_ai_provider_connectivity.py` | Staging AI provider connectivity smoke; its AC lives in the `testing` package roadmap (AC-testing.deploy-gates.27, `common/testing/contract.py`) |
| `tests/e2e/test_ac_authority_tiers_epic026.py` | EPIC-026 authority-tier pipeline product owner E2E; AC-authority.2.1/AC-authority.3.1/AC-authority.4.1 references live in the test file |
| `tests/e2e/test_application_ai_advisor_epic021.py` | Application AI Advisor product owner E2E; AC21.1 references live in the test file |
| `tests/e2e/test_auth_flows.py` | Deployed auth flow E2E; AC references live in the test file |
| `tests/e2e/test_brokerage_upload_to_portfolio_value.py` | Critical proof: AC-extraction.813.10 |
| `tests/e2e/test_core_journeys.py` | Deployed core journey E2E; AC references live in the test file |
| `tests/e2e/test_e2e_flows.py` | Deployed extended flow E2E; AC references live in the test file |
| `tests/e2e/test_four_asset_net_worth_golden_path.py` | Critical proof: AC-testing.product-gates.7, AC-extraction.813.10, AC5.7.3, AC11.9.1-AC11.9.3, AC17.5.4 |
| `tests/e2e/test_llm_provider_abstraction_epic023.py` | LLM provider abstraction product owner E2E; EPIC-023 / AC23.1 references live in the test file |
| `tests/e2e/test_frontend_observability_epic024.py` | EPIC-024 frontend browser observability product owner E2E; AC24.1.1 reference lives in the test file |
| `tests/e2e/test_market_data_price_paths.py` | Critical proof; ACs live in the `pricing` package roadmap (`AC-pricing.marketdata.7`, `AC-pricing.marketdata.11`, `common/pricing/contract.py`) |
| `tests/e2e/test_personal_financial_report_package.py` | Critical proof: AC5.1.1, AC5.1.4, AC5.2.3, AC5.3.1, AC5.8.1, AC5.12.4, AC5.13.4-AC5.13.5, AC11.8.3, AC11.9.1-AC11.9.3, AC11.11.1-AC11.11.2, AC17.10.1-AC17.10.2, AC17.12.1-AC17.12.3, AC-testing.product-gates.8, AC-testing.product-gates.9, AC-testing.product-gates.10, AC-testing.product-gates.11, AC-testing.product-gates.12 |
| `tests/e2e/test_production_readonly_smoke.py` | Production-readonly smoke E2E; AC references live in the test file |
| `tests/e2e/test_statement_full_journey.py` | Critical proof: AC-extraction.813.11 |
| `tests/e2e/test_statement_upload_e2e.py` | Statement upload E2E; AC references live in the test file |
| `tests/e2e/test_version_check.py` | Version/runtime E2E; AC references live in the test file |
| `tests/e2e/test_vision_upload_to_dashboard_hard_gate.py` | Critical proof: AC-testing.product-gates.2, AC-testing.product-gates.3, AC-testing.product-gates.4, AC-testing.product-gates.5, AC-testing.product-gates.6 |

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

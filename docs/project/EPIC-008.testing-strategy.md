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
  The migrated AC8.13.x requirement definitions and proof mappings are
  maintained in the `testing` package roadmap
  (`common/testing/contract.py`); the few rows still EPIC-owned live in
  the Test Cases table below. Neither is duplicated in this strategy
  overview.

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
| AC Traceability Gate | Real AC references in CI-required execution stages | `tools/check_ac_index.py`, `common/testing/data/test-execution-matrix.yaml`, `tools/check_e2e_epic_traceability.py` | Fail closed when mandatory AC is missing, stub-only, placeholder-only, or real-only outside required execution |

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
| Critical E2E proof paths | `tools/check_ac_index.py` (derived view of [critical-proof-outcomes.yaml](../../common/testing/data/critical-proof-outcomes.yaml)) |
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

CI execution shape is owned by [ci-cd.md](../../common/testing/ci-cd.md), workflows, and
[test-execution-matrix.yaml](../../common/testing/data/test-execution-matrix.yaml). Do not copy
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

> (AC8.4.1 removed and AC8.4.2 removed and AC8.4.3 removed, canonical: migrated
> to the `extraction` package roadmap as `AC-extraction.804.1-3`, #1821 Wave A.)

### AC8.5: Phase 4 - Reconciliation Engine

> This group's rows removed — migrated to the `reconciliation` package
> roadmap as `AC-reconciliation.reconciliation-engine.1-3` (migration
> closeout continuation, #1663 / #1711).

### AC8.6: Phase 5 - Reporting & Visualization

> This group's rows removed — migrated to the `reporting` package roadmap as
> `AC-reporting.journeys.1-4` (migration closeout continuation, #1663 /
> #1716).

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

> **Mostly migrated.** The extraction-owned rows (AC8.13.1 removed, canonical:
> homed in the `extraction` package roadmap as `AC-extraction.813.10` / `.11` /
> `.12` — covering the DBS full-journey browser test, the statement-upload
> full-flow browser test, and the multi-brokerage import test — in
> [`common/extraction/contract.py`](../../common/extraction/contract.py),
> migration closeout wave 3, #1663). The CI/CD, deploy-gate, preview,
> classifier, coverage, AC-index, governance, toolchain, schema, and
> test-lifecycle rows migrated into the `testing` package roadmap
> ([`common/testing/contract.py`](../../common/testing/contract.py)) as
> `AC-testing.<sub-theme>.<seq>` ids (migration closeout, #1663 / #1718);
> the per-row canonical pointers are listed after the table below.
>
> **Rows that stay in this EPIC** (marker note, #1718 / #1821):
>
> - (AC8.13.18 removed and AC8.13.19 removed — reporting-owned brokerage
>   portfolio valuation semantics, migrated to the reporting bucket, #1716 /
>   #1821.)
> - The five frontend-only (Vitest/Playwright) coverage/deploy-metadata rows
>   in this group migrated to `testing`/`runtime` in #1821 Wave B once
>   #1820/#1825 gave the governance gate TS test-ref resolution (see the
>   migration note below).
> - AC8.13.61 - AC8.13.63 are archive-residual ownership rows whose proofs
>   assert EPIC-008 residency by design (and AC8.13.61 is P3, which the
>   package `ACRecord` priority vocabulary does not carry); they are
>   re-homed by the final cleanup, #1719.
> - (AC8.13.164 removed and AC8.13.165 removed — evidence bundle, cites a
>   proving test that drives the cassette graded-eval corpus, which the
>   authority classifier bands LLM; migrated to the `llm` package instead of
>   `testing`, #1821.)

> (AC8.13.18 removed and AC8.13.19 removed, canonical: migrated to the
> `reporting` package roadmap as `AC-reporting.portfolio-valuation-gate.1-2`,
> #1821 Wave A.)

(AC8.13.48 removed and AC8.13.76 removed and AC8.13.82 removed and AC8.13.92 removed, canonical: migrated to the `testing` package roadmap as `AC-testing.fe-coverage.1` through `.4`, #1821 Wave B)
| AC8.13.61 | Visual regression residual is explicitly owned by EPIC-008 as a P3 future testing capability | `test_AC8_13_61_visual_regression_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P3 | <!-- epic-owned: horizontal -->
| AC8.13.62 | Test observability residuals are explicitly owned by EPIC-008 with current replacements and future dashboard/notification/trend scope | `test_AC8_13_62_test_observability_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P2 | <!-- epic-owned: horizontal -->
| AC8.13.63 | Performance testing residual is explicitly owned by EPIC-008 with current Locust/staging coverage and future P95 trend gate scope | `test_AC8_13_63_performance_testing_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P2 | <!-- epic-owned: horizontal -->
(AC8.13.90 removed, canonical: migrated to the `runtime` package roadmap as `AC-runtime.fe-deploy.1`, #1821 Wave B)
> (AC8.13.164 removed and AC8.13.165 removed, canonical: migrated to the `llm`
> package roadmap as `AC-llm.evidence-bundle.1-2` — routed to `llm` not
> `testing` because the authority classifier bands
> tests/tooling/test_evidence_bundle.py LLM, which would trip
> `check_authority_reconcile.py` under `testing`'s declared CODE-ONLY tier;
> #1821 Wave A.)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
> (AC8.13.166 removed and AC8.13.167 removed, canonical: migrated to the `testing` package roadmap as `AC-testing.deploy-gates.41` and `.42`, #1821 Wave A)

> (AC8.13.6 removed, canonical: migrated to `AC-testing.product-gates.1`.)
> (AC8.13.9 removed, canonical: migrated to `AC-testing.deploy-gates.1`.)
> (AC8.13.11 removed, canonical: migrated to `AC-testing.deploy-gates.2`.)
> (AC8.13.12 removed, canonical: migrated to `AC-testing.deploy-gates.3`.)
> (AC8.13.13 removed, canonical: migrated to `AC-testing.deploy-gates.4`.)
> (AC8.13.14 removed, canonical: migrated to `AC-testing.deploy-gates.5`.)
> (AC8.13.15 removed, canonical: migrated to `AC-testing.coverage.1`.)
> (AC8.13.16 removed, canonical: migrated to `AC-testing.classifier.1`.)
> (AC8.13.17 removed, canonical: migrated to `AC-testing.acgates.1`.)
> (AC8.13.20 removed, canonical: migrated to `AC-testing.classifier.2`.)
> (AC8.13.21 removed, canonical: migrated to `AC-testing.deploy-gates.6`.)
> (AC8.13.22 removed, canonical: migrated to `AC-testing.deploy-gates.7`.)
> (AC8.13.23 removed, canonical: migrated to `AC-testing.deploy-gates.8`.)
> (AC8.13.24 removed, canonical: migrated to `AC-testing.acgates.2`.)
> (AC8.13.25 removed, canonical: migrated to `AC-testing.ci-structure.1`.)
> (AC8.13.26 removed, canonical: migrated to `AC-testing.ci-structure.2`.)
> (AC8.13.27 removed, canonical: migrated to `AC-testing.coverage.2`.)
> (AC8.13.28 removed, canonical: migrated to `AC-testing.product-gates.2`.)
> (AC8.13.29 removed, canonical: migrated to `AC-testing.product-gates.3`.)
> (AC8.13.30 removed, canonical: migrated to `AC-testing.product-gates.4`.)
> (AC8.13.31 removed, canonical: migrated to `AC-testing.product-gates.5`.)
> (AC8.13.32 removed, canonical: migrated to `AC-testing.product-gates.6`.)
> (AC8.13.33 removed, canonical: migrated to `AC-testing.ci-structure.3`.)
> (AC8.13.34 removed, canonical: migrated to `AC-testing.ci-structure.4`.)
> (AC8.13.35 removed, canonical: migrated to `AC-testing.acgates.3`.)
> (AC8.13.36 removed, canonical: migrated to `AC-testing.deploy-gates.9`.)
> (AC8.13.37 removed, canonical: migrated to `AC-testing.acgates.4`.)
> (AC8.13.38 removed, canonical: migrated to `AC-testing.preview.1`.)
> (AC8.13.39 removed, canonical: migrated to `AC-testing.toolchain.1`.)
> (AC8.13.40 removed, canonical: migrated to `AC-testing.deploy-gates.10`.)
> (AC8.13.41 removed, canonical: migrated to `AC-testing.acgates.5`.)
> (AC8.13.42 removed, canonical: migrated to `AC-testing.product-gates.7`.)
> (AC8.13.44 removed, canonical: migrated to `AC-testing.toolchain.2`.)
> (AC8.13.45 removed, canonical: migrated to `AC-testing.toolchain.3`.)
> (AC8.13.46 removed, canonical: migrated to `AC-testing.preview.2`.)
> (AC8.13.47 removed, canonical: migrated to `AC-testing.governance.1`.)
> (AC8.13.49 removed, canonical: migrated to `AC-testing.deploy-gates.11`.)
> (AC8.13.50 removed, canonical: migrated to `AC-testing.acgates.6`.)
> (AC8.13.51 removed, canonical: migrated to `AC-testing.deploy-gates.12`.)
> (AC8.13.52 removed, canonical: migrated to `AC-testing.deploy-gates.13`.)
> (AC8.13.53 removed, canonical: migrated to `AC-testing.toolchain.4`.)
> (AC8.13.54 removed, canonical: migrated to `AC-testing.acgates.7`.)
> (AC8.13.55 removed, canonical: migrated to `AC-testing.deploy-gates.14`.)
> (AC8.13.56 removed, canonical: migrated to `AC-testing.toolchain.5`.)
> (AC8.13.57 removed, canonical: migrated to `AC-testing.toolchain.6`.)
> (AC8.13.58 removed, canonical: migrated to `AC-testing.toolchain.7`.)
> (AC8.13.59 removed, canonical: migrated to `AC-testing.toolchain.8`.)
> (AC8.13.60 removed, canonical: migrated to `AC-testing.deploy-gates.15`.)
> (AC8.13.64 removed, canonical: migrated to `AC-testing.deploy-gates.16`.)
> (AC8.13.65 removed, canonical: migrated to `AC-testing.deploy-gates.17`.)
> (AC8.13.66 removed, canonical: migrated to `AC-testing.coverage.3`.)
> (AC8.13.67 removed, canonical: migrated to `AC-testing.deploy-gates.18`.)
> (AC8.13.68 removed, canonical: migrated to `AC-testing.acgates.8`.)
> (AC8.13.69 removed, canonical: migrated to `AC-testing.lifecycle.1`.)
> (AC8.13.70 removed, canonical: migrated to `AC-testing.acgates.9`.)
> (AC8.13.71 removed, canonical: migrated to `AC-testing.preview.3`.)
> (AC8.13.72 removed, canonical: migrated to `AC-testing.preview.4`.)
> (AC8.13.73 removed, canonical: migrated to `AC-testing.preview.5`.)
> (AC8.13.74 removed, canonical: migrated to `AC-testing.preview.6`.)
> (AC8.13.75 removed, canonical: migrated to `AC-testing.coverage.4`.)
> (AC8.13.77 removed, canonical: migrated to `AC-testing.acgates.10`.)
> (AC8.13.78 removed, canonical: migrated to `AC-testing.acgates.11`.)
> (AC8.13.79 removed, canonical: migrated to `AC-testing.toolchain.9`.)
> (AC8.13.80 removed, canonical: migrated to `AC-testing.acgates.12`.)
> (AC8.13.81 removed, canonical: migrated to `AC-testing.governance.2`.)
> (AC8.13.83 removed, canonical: migrated to `AC-testing.product-gates.8`.)
> (AC8.13.84 removed, canonical: migrated to `AC-testing.product-gates.9`.)
> (AC8.13.85 removed, canonical: migrated to `AC-testing.product-gates.10`.)
> (AC8.13.86 removed, canonical: migrated to `AC-testing.ci-structure.5`.)
> (AC8.13.87 removed, canonical: migrated to `AC-testing.product-gates.11`.)
> (AC8.13.88 removed, canonical: migrated to `AC-testing.product-gates.12`.)
> (AC8.13.89 removed, canonical: migrated to `AC-testing.preview.7`.)
> (AC8.13.93 removed, canonical: migrated to `AC-testing.deploy-gates.19`.)
> (AC8.13.94 removed, canonical: migrated to `AC-testing.governance.3`.)
> (AC8.13.95 removed, canonical: migrated to `AC-testing.governance.4`.)
> (AC8.13.96 removed, canonical: migrated to `AC-testing.classifier.3`.)
> (AC8.13.97 removed, canonical: migrated to `AC-testing.classifier.4`.)
> (AC8.13.98 removed, canonical: migrated to `AC-testing.preview.8`.)
> (AC8.13.99 removed, canonical: migrated to `AC-testing.toolchain.10`.)
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
> (AC8.13.118 removed, canonical: migrated to `AC-testing.governance.5`.)
> (AC8.13.119 removed, canonical: migrated to `AC-testing.deploy-gates.26`.)
> (AC8.13.120 removed, canonical: migrated to `AC-testing.deploy-gates.27`.)
> (AC8.13.121 removed, canonical: migrated to `AC-testing.schema.1`.)
> (AC8.13.122 removed, canonical: migrated to `AC-testing.schema.2`.)
> (AC8.13.123 removed, canonical: migrated to `AC-testing.schema.3`.)
> (AC8.13.124 removed, canonical: migrated to `AC-testing.acgates.13`.)
> (AC8.13.125 removed, canonical: migrated to `AC-testing.preview.15`.)
> (AC8.13.126 removed, canonical: migrated to `AC-testing.governance.6`.)
> (AC8.13.127 removed, canonical: migrated to `AC-testing.schema.4`.)
> (AC8.13.128 removed, canonical: migrated to `AC-testing.schema.5`.)
> (AC8.13.129 removed, canonical: migrated to `AC-testing.schema.6`.)
> (AC8.13.130 removed, canonical: migrated to `AC-testing.schema.7`.)
> (AC8.13.131 removed, canonical: migrated to `AC-testing.governance.7`.)
> (AC8.13.132 removed, canonical: migrated to `AC-testing.governance.8`.)
> (AC8.13.133 removed, canonical: migrated to `AC-testing.governance.9`.)
> (AC8.13.134 removed, canonical: migrated to `AC-testing.governance.10`.)
> (AC8.13.135 removed, canonical: migrated to `AC-testing.acgates.14`.)
> (AC8.13.136 removed, canonical: migrated to `AC-testing.secret-scan.1`.)
> (AC8.13.137 removed, canonical: migrated to `AC-testing.deploy-gates.28`.)
> (AC8.13.138 removed, canonical: migrated to `AC-testing.acgates.15`.)
> (AC8.13.139 removed, canonical: migrated to `AC-testing.acgates.16`.)
> (AC8.13.140 removed, canonical: migrated to `AC-testing.acgates.17`.)
> (AC8.13.141 removed, canonical: migrated to `AC-testing.acgates.18`.)
> (AC8.13.142 removed, canonical: migrated to `AC-testing.gate-inventory.1`.)
> (AC8.13.143 removed, canonical: migrated to `AC-testing.coverage.5`.)
> (AC8.13.144 removed, canonical: migrated to `AC-testing.deploy-gates.29`.)
> (AC8.13.145 removed, canonical: migrated to `AC-testing.ci-structure.6`.)
> (AC8.13.146 removed, canonical: migrated to `AC-testing.deploy-gates.30`.)
> (AC8.13.147 removed, canonical: migrated to `AC-testing.ci-structure.7`.)
> (AC8.13.148 removed, canonical: migrated to `AC-testing.ci-structure.8`.)
> (AC8.13.149 removed, canonical: migrated to `AC-testing.ci-structure.9`.)
> (AC8.13.150 removed, canonical: migrated to `AC-testing.gate-inventory.2`.)
> (AC8.13.151 removed, canonical: migrated to `AC-testing.gate-inventory.3`.)
> (AC8.13.152 removed, canonical: migrated to `AC-testing.classifier.9`.)
> (AC8.13.153 removed, canonical: migrated to `AC-testing.gate-inventory.4`.)
> (AC8.13.154 removed, canonical: migrated to `AC-testing.gate-inventory.5`.)
> (AC8.13.155 removed, canonical: migrated to `AC-testing.gate-inventory.6`.)
> (AC8.13.156 removed, canonical: migrated to `AC-testing.deploy-gates.31`.)
> (AC8.13.157 removed, canonical: migrated to `AC-testing.deploy-gates.32`.)
> (AC8.13.158 removed, canonical: migrated to `AC-testing.deploy-gates.33`.)
> (AC8.13.159 removed, canonical: migrated to `AC-testing.deploy-gates.34`.)
> (AC8.13.160 removed, canonical: migrated to `AC-testing.deploy-gates.35`.)
> (AC8.13.161 removed, canonical: migrated to `AC-testing.classifier.10`.)
> (AC8.13.162 removed, canonical: migrated to `AC-testing.ci-structure.10`.)
> (AC8.13.163 removed, canonical: migrated to `AC-testing.coverage.6`.)

### AC8.14: Product Trust Proof Mirrors

> (AC8.14.1 removed, canonical: migrated to `AC-testing.trust-mirrors.1`.)
> (AC8.14.2 removed, canonical: migrated to `AC-testing.trust-mirrors.2`.)
> (AC8.14.3 removed, canonical: migrated to `AC-testing.trust-mirrors.3`.)
> (AC8.14.4 removed, canonical: migrated to `AC-testing.trust-mirrors.4`.)

### AC8.15: Full-Year Statement-to-Report End-to-End Acceptance

Closing gate for the **Usable** milestone (G2∩G3, [#950](https://github.com/wangzitian0/finance_report/issues/950)): AC-testing.trust-mirrors.4 mirrors the ledger→report leg from *manual* entries in a *single* period; this group proves the **assembled** pipeline — statement parse → Stage-1 approval (balance-chain validated) → auto-posted ledger entries → period reports — ties out across **multiple months**. Deterministic by construction (rule-based CSV parse, no LLM; no AI classification, so counter-accounts fall back to `Income - Uncategorized` / `Expense - Uncategorized`).

> This group's rows removed — migrated to the `reporting` package roadmap as
> `AC-reporting.full-year.1-2` (migration closeout continuation, #1663 /
> #1716).

### AC8.16: Augmentation-Layer Report Integrity

AC8.14/AC8.15 pin the *core accounting arithmetic*. This group pins the newer
**augmentation layer** — confidence-tagged extracted/reconciled inputs and
append-only manual-valuation versioning — where the recent audit bugs lived
([#968](https://github.com/wangzitian0/finance_report/issues/968) superseded
valuation leaked into holdings; a missing `.distinct()` inflated provenance).
It stands up the *combined* state production actually has (a low-confidence ledger
input AND a corrected/superseded valuation present at once) and asserts the report
is right on every axis simultaneously. Part of [#990](https://github.com/wangzitian0/finance_report/issues/990) (report-input integrity).

> This group's rows removed — migrated to the `reporting` package roadmap as
> `AC-reporting.augmentation.1-2` (migration closeout continuation, #1663 /
> #1716). The `@ac_proof` decorator, `ac_evidence` records, and the
> ac-score-baseline entry moved to the new ids with them.

**Traceability Ownership**:
- This table owns the intended AC-to-proof mapping for EPIC-008.
- Current AC counts, covered/untested totals, and placeholder/stub exclusions are
  owned by `python tools/analyze_test_ac_coverage.py --no-write --stdout` and
  CI traceability artifacts.
- Mandatory AC gate behavior is owned by `python tools/check_ac_index.py`.
- Test path execution status for AC proof is owned by
  [test-execution-matrix.yaml](../../common/testing/data/test-execution-matrix.yaml).
- Default AC traceability test-surface directories are owned by
  `common/testing/test_surface.py` and consumed by both the fail-closed gate and
  generated audit builder.
- Critical product proof-path anchoring is owned by
  the derived critical-proof matrix (macro outcome source `common/testing/data/critical-proof-outcomes.yaml`) and
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

(AC8.19.1 removed, canonical: migrated to the `identity` package roadmap as `AC-identity.fe-auth2.2`, #1821 Wave B)

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
non-PR events. The classification rule is owned by [ci-cd.md](../../common/testing/ci-cd.md).

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

Which tests run where was previously scattered: `common/testing/data/test-execution-matrix.yaml`
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
| Test path -> execution stage mapping | [test-execution-matrix.yaml](../../common/testing/data/test-execution-matrix.yaml) |
| Product E2E function -> EPIC ownership | `tools/check_e2e_epic_traceability.py` |
| Mandatory AC proof eligibility | `tools/check_ac_index.py` |
| Critical macro outcome proof | `tools/check_ac_index.py` (derived view of [critical-proof-outcomes.yaml](../../common/testing/data/critical-proof-outcomes.yaml)) |

Product E2E ownership index:

| File | Ownership anchor |
|---|---|
| `apps/backend/tests/e2e/test_core_journeys.py` | Backend core journey E2E; AC8.1-AC8.12 references live in the test file |
| `apps/backend/tests/e2e/test_business_value_correctness_gate.py` | #1505 Tier-1 twin: `AC-reporting.business-value-gate.1`/`.2` (real business-value totals + the #1481 invariant), `common/reporting/contract.py` |
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
| `tests/e2e/test_four_asset_net_worth_golden_path.py` | Critical proof: AC-testing.product-gates.7, AC-extraction.813.10, AC-reporting.net-worth-timeseries.2, AC-pricing.manualvaluation.5, AC-pricing.manualvaluation.6, AC-pricing.manualvaluation.7, AC-portfolio.valuation.1 |
| `tests/e2e/test_llm_provider_abstraction_epic023.py` | LLM provider abstraction product owner E2E; EPIC-023 / AC23.1 references live in the test file |
| `tests/e2e/test_frontend_observability_epic024.py` | EPIC-024 frontend browser observability product owner E2E |
| `tests/e2e/test_market_data_price_paths.py` | Critical proof; ACs live in the `pricing` package roadmap (`AC-pricing.marketdata.7`, `AC-pricing.marketdata.11`, `common/pricing/contract.py`) |
| `tests/e2e/test_personal_financial_report_package.py` | Critical proof: AC-reporting.balance-sheet.1, AC-reporting.balance-sheet.4, AC-reporting.income-statement.3, AC-reporting.cash-flow.1, AC-reporting.fe-viz-reports.2, AC-reporting.package-notes.3, AC-reporting.package-traceability.3, AC-reporting.package-traceability.4, AC-reporting.annualized-dashboard.2, AC-pricing.manualvaluation.5, AC-pricing.manualvaluation.6, AC-pricing.manualvaluation.7, AC-reporting.package-annualized.3, AC-reporting.package-annualized.4, AC-portfolio.report-schedule.1, AC-portfolio.report-schedule.2, AC-portfolio.fixtures.1, AC-portfolio.fixtures.2, AC-portfolio.fixtures.3, AC-testing.product-gates.8, AC-testing.product-gates.9, AC-testing.product-gates.10, AC-testing.product-gates.11, AC-testing.product-gates.12 |
| `tests/e2e/test_production_readonly_smoke.py` | Production-readonly smoke E2E; AC references live in the test file |
| `tests/e2e/test_business_value_correctness_gate.py` | #1505 Tier-2/3 deploy-gate twin (in-runner preview lane, no LLM/market-data/persistent-env dependency): `AC-reporting.business-value-gate.1`/`.2`, `common/reporting/contract.py` |
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
  compatibility. This closes #783 and is now documented through AC-testing.preview.10.
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
   readers would still pass only by route alias mismatch: fixed by AC-testing.preview.10.
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
[ci-cd.md](../../common/testing/ci-cd.md), `.github/workflows/*.yml`, and the corresponding
tooling tests.

### 5.5 Known Gaps

Known testing gaps are not maintained as detailed status narratives here. Use
these owners instead:

| Gap type | Owner |
|---|---|
| Personal report package proof contract | `tools/check_ac_index.py` (derived view; macro outcome source [critical-proof-outcomes.yaml](../../common/testing/data/critical-proof-outcomes.yaml)), #573/#649, `tests/tooling/test_personal_report_package_fixture_contract.py` |
| Provider-backed staging AI/OCR gates | [ci-cd.md](../../common/testing/ci-cd.md), staging workflow artifacts |
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

- [../ssot/coverage.md](../../common/testing/coverage.md) — coverage policy semantics.
- [../ssot/ci-cd.md](../../common/testing/ci-cd.md) — CI gate semantics.
- Environment smoke-test rationale and command semantics — migrated out of this EPIC into the `runtime` package: [../../common/runtime/readme.md](../../common/runtime/readme.md).
- [Backend tests README](https://github.com/wangzitian0/finance_report/blob/main/apps/backend/tests/README.md) — backend test-suite navigation.

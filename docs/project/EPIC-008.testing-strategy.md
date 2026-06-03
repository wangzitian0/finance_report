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
- An AC counts as "covered" when it has a **passing Tier 1+ test** that exercises the real code path (not a mock/stub).
- Tier 2/3 tests that `skip` due to missing env vars (e.g., `FRONTEND_URL`) do NOT count toward coverage.
- The **AC pass rate** = (ACs with at least one passing Tier 1+ test) / (Total ACs).
- CI source coverage uses the shared coverage policy in `common/coverage/policy.py`. New backend, frontend, common, and tools modules are expected to appear in the matching LCOV report unless the policy explicitly excludes them.
- **AC8.13.15**: Unified coverage policy keeps CI source tree, LCOV reports, and Coveralls uploads aligned.
- **AC8.13.16**: CI change classification skips backend/frontend/coverage for lightweight changes and uses deterministic npm cache.
- **AC8.13.17**: AC registry generation preserves canonical descriptions and stores entries under ACx.y merge anchors without committed totals.
- **AC8.13.18**: Brokerage portfolio gate validates market valuation adjustment lines even when unrelated asset lines lower total assets.
- **AC8.13.19**: Brokerage portfolio gate failures include holdings, valuation adjustment, non-portfolio asset, and balance-sheet diagnostics.
- **AC8.13.20**: CI change classification is covered by multi-commit and markdown edge-case regression tests.
- **AC8.13.21**: Provider-backed post-merge AI/OCR gate runs only after a successful main CI `workflow_run`.
- **AC8.13.22**: Staging deploy starts from successful main CI `workflow_run` before building or deploying.
- **AC8.13.23**: Automatic staging deploy health and AI/OCR validation run in one serialized post-merge workflow unit.
- **AC8.13.24**: AC traceability audit is uploaded as a CI artifact instead of failing on a stale committed report.
- **AC8.13.25**: Backend tests and AC traceability start without waiting for lint when their own prerequisites are ready.
- **AC8.13.26**: CI metrics contract fails when source roots, coverage policy, workflow gates, or AC traceability semantics drift.
- **AC8.13.27**: Pull requests do not publish Coveralls status contexts; main-only Coveralls reporting remains separate from local deterministic coverage gates.
- **AC8.13.28**: Deterministic upload-to-dashboard gate runs as a critical fresh-user staging E2E.
- **AC8.13.29**: Stage 1 review auto-posts journal entries from the deterministic fixture.
- **AC8.13.30**: Reconciliation rerun is idempotent and Stage 2 run review reaches a cleared completion state.
- **AC8.13.31**: Processing Account summary and pending page stay visible and correct for the cleared run.
- **AC8.13.32**: Dashboard, balance sheet, income statement, and cash-flow totals exactly match the deterministic upload fixture.
- **AC8.13.33**: Shared E2E setup caches Python virtualenv and Playwright browser artifacts for staging and preview gates.
- **AC8.13.34**: CI and post-merge workflows append queue, execution, and per-job timing summaries to GitHub Step Summary.
- **AC8.13.35**: AC traceability reporting distinguishes real test references from `_ac_stubs` and trivial placeholder assertions.
- **AC8.13.36**: Main CI builds SHA-tagged staging images and post-merge staging reuses them after CI workflow success.
- **AC8.13.37**: AC traceability fails mandatory ACs that are covered only by `_ac_stubs`.
- **AC8.13.38**: Scheduled PR preview cleanup removes stale closed-PR VPS resources while preserving open PR previews.
- **AC8.13.39**: Runtime and container versions stay aligned across local, CI, and Docker environments.
- **AC8.13.40**: PR CI dry-runs staging image builds before merge; main push CI is the only path that pushes SHA-tagged images.
- **AC8.13.41**: Critical proof matrix fails when a core product proof path is backed only by broad or reference-only AC strings.
- **AC8.13.42**: Four-asset as-of net worth golden path runs as a critical fresh-user post-merge E2E.
- **AC8.13.43**: Failed main CI workflow_run reports current staging state without deploying.
- **AC8.13.44**: Local bootstrap provides one command for runtimes, dependency setup, pre-commit hooks, and container-runtime diagnostics.
- **AC8.13.45**: Local verification entry points fail on the same backend format errors and route `make test` through the root Moon test command without hashing the infra submodule gitlink as a file input.
- **AC8.13.46**: PR preview non-LLM E2E uses the same strict, parallel gate shape as staging non-LLM E2E.
- **AC8.13.47**: Remaining delivery-engine optimizations are captured in a tracked project recommendation note.
- **AC8.13.48**: Frontend gap tests cover route, component, and API helper paths so frontend LCOV line coverage reaches 99%.
- **AC8.13.49**: Staging AI/OCR gates publish audit input inventory and replay summary fields.
- **AC8.13.50**: Critical proof matrix validates the closed macro outcome set from README through owner EPICs and E2E proof anchors.
- **AC8.13.51**: Automatic staging deploy uses successful main CI `workflow_run`, with no in-job CI polling.
- **AC8.13.52**: Production release dry-run validates release prerequisites and image builds without production mutation.
- **AC8.13.53**: Common owns SSOT, config and CI contracts, coverage policy, and isolation helpers; command entry points and tool-owned implementations live in `tools/`.
- **AC8.13.54**: Critical proof matrix fails when README macro outcomes, matrix outcomes, or owner EPIC reverse declarations drift.
- **AC8.13.55**: Post-merge staging deploys only for runtime, deploy, E2E, staging workflow, toolchain, or infra-submodule changes.
- **AC8.13.56**: Coverage command entry points run from `tools/`; the shared policy stays in `common/coverage/policy.py`, and command implementations live under `tools/_lib/coverage/`.
- **AC8.13.57**: SSOT and AC command entry points run from `tools/` while shared implementations live under `common/ssot/`.
- **AC8.13.58**: CI and toolchain command entry points run from `tools/`; reusable contracts stay under `common/ci/`, while report and shell command implementations live under `tools/_lib/`.
- **AC8.13.59**: Config validation command entry points run from `tools/` while shared implementations live under `common/config/`.
- **AC8.13.77**: Registry-to-EPIC consistency fails active stub or orphan AC entries instead of silently excluding them.
- **AC8.13.78**: Mandatory AC traceability requires at least one real proof file that is mapped to a CI-required execution stage.
- **AC8.13.79**: Local E2E command routing distinguishes root deployment E2E from backend Tier-1 API E2E.
- **AC8.13.80**: AC coverage analysis supports no-write and stale-report check modes for local verification.
- **AC8.13.81**: Coverage threshold documentation links to code-owned thresholds instead of copying mutable numeric values.
- **AC8.13.60**: Deploy workflows do not keep no-op dependency checks or warning-only performance probes that cannot block release risk.
- **AC8.13.61**: Visual regression residual is explicitly owned by EPIC-008 as a P3 future testing capability.
- **AC8.13.62**: Test observability residuals are explicitly owned by EPIC-008 with current replacements and future dashboard/notification/trend scope.
- **AC8.13.64**: Production release verifies DB, S3, API, frontend, and SigNoz health before completing deploy.
- **AC8.13.65**: Production release reuses successful main CI proof instead of rerunning container-backed tests in the release lane.
- **AC8.13.66**: Coveralls uploads strip branch counters so external percentages track the line-only unified coverage gate.
- **AC8.13.67**: Production release preserves deployed version metadata from image build through Dokploy runtime health.
- **AC8.13.68**: E2E EPIC traceability fails E2E-root test functions missing function-level EPIC IDs or project EPICs without E2E owners.
- **AC8.13.69**: Local test lifecycle binds namespaced infra to ephemeral host ports so parallel branches do not collide.
- **AC8.13.70**: E2E EPIC traceability fails README EPIC map drift and unclassified E2E-like assets outside declared roots.
- **AC8.13.71**: One lifecycle tool owns PR preview deploy, stop, cleanup, reconciliation, and stable metadata.
- **AC8.13.72**: Dokploy deploy diagnostics redact raw responses and log only allowlisted effective environment diffs.
- **AC8.13.73**: VPS host hygiene is a Dokploy server schedule that prunes generic Docker and journal garbage while keeping PR preview resources from the last 3 days or the most recent 3 PRs.
- **AC8.13.74**: Scheduled PR preview cleanup is limited to closed-PR reconciliation and no longer owns generic host hygiene.
- **AC8.13.75**: Reporting-only coverage gate summary cannot fail the final CI aggregation job if GitHub Step Summary writes fail.

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
Use `docs/analysis/test-ac-coverage-report.md`,
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

## 3. Core Use Cases (100 Scenarios)

These scenarios represent the "Vertical Slices" of user value.

### Phase 1: Onboarding & Account Structure (1-10)
- [x] **New User Registration**: User signs up with email/password, verifies email, and lands on dashboard. *(test_core_journeys.py::test_register_and_login_flow)*
- [ ] **Setup Base Currency**: User selects SGD as base currency during onboarding.
- [x] **Create Cash Account**: User creates a "Wallet" asset account (SGD). *(test_core_journeys.py::test_create_cash_account)*
- [x] **Create Bank Account**: User creates a "DBS Savings" asset account (SGD). *(test_core_journeys.py::test_create_bank_account)*
- [ ] **Create Credit Card**: User creates a "Citi Rewards" liability account (SGD).
- [ ] **Create Multi-currency Account**: User creates a "Wise USD" asset account (USD).
- [ ] **Define Custom Expense Category**: User adds "Coffee Subscription" under "Expenses".
- [ ] **Define Income Source**: User adds "Freelance Design" under "Income".
- [ ] **Archive Account**: User archives an old "Student Account" (hidden from lists).
- [ ] **Reactivate Account**: User restores the "Student Account" for historical reference.

### Phase 2: Manual Journal Entries (11-30)
- [x] **Simple Expense**: User pays $5.00 for coffee using "Wallet" (Manual Entry). *(test_core_journeys.py::test_simple_expense_entry)*
- [x] **Income Recording**: User records $5,000 salary deposit into "DBS Savings". *(test_core_journeys.py::test_income_recording)*
- [x] **Credit Card Spend**: User buys a laptop ($2,000) using "Citi Rewards". *(test_core_journeys.py::test_credit_card_spend)*
- [x] **Credit Card Repayment**: User pays off "Citi Rewards" ($2,000) from "DBS Savings". *(test_core_journeys.py::test_credit_card_repayment)*
- [x] **Internal Transfer**: User moves $500 from "DBS Savings" to "Wallet" (ATM Withdrawal). *(test_core_journeys.py::test_internal_transfer)*
- [x] **Split Transaction**: User spends $100 at supermarket: $80 "Groceries", $20 "Household" (1 Debit, 2 Credits). *(test_core_journeys.py::test_split_transaction)*
- [ ] **Refund Processing**: User receives $50 refund to "Citi Rewards" for returned item.
- [ ] **Foreign Expense (Manual FX)**: User spends 10 USD on "Wise USD", records as 13.50 SGD equivalent.
- [x] **Void Entry**: User voids a duplicate coffee transaction (System generates reversal). *(test_core_journeys.py::test_void_journal_entry)*
- [x] **Post Draft**: User saves a complex entry as "Draft", reviews later, and "Posts" it. *(test_core_journeys.py::test_post_draft_entry)*
- [ ] **Recurring Subscription**: User sets up monthly $15 Netflix bill (Template/Copy).
- [ ] **Asset Purchase**: User buys a car, recording asset increase and loan liability increase.
- [ ] **Depreciation Entry**: User manually records monthly depreciation for the laptop.
- [ ] **Dividend Income**: User records stock dividend received in "DBS Savings".
- [ ] **Tax Payment**: User records income tax payment from "DBS Savings".
- [ ] **Loan Interest**: User records monthly mortgage payment (Split: Principal + Interest).
- [ ] **Gift Received**: User records cash gift into "Wallet".
- [ ] **Lost Cash**: User records "Misc Expense" for lost $10 note.
- [ ] **Opening Balance**: User sets initial balance for "DBS Savings" (Equity adjustment).
- [ ] **Year-End Closing**: User (symbolically) reviews P&L reset (though system is continuous).

### Phase 3: Statement Import & Parsing (31-50)
- [ ] **Import DBS CSV**: User uploads standard DBS CSV; system parses date, amount, description.
- [ ] **Import Citi PDF**: User uploads Citi PDF; system extracts transaction table.
- [ ] **Import Wise JSON**: User uploads custom JSON export from Wise.
- [ ] **Duplicate Detection**: User uploads same DBS CSV twice; system rejects duplicates.
- [ ] **Malformed File Handling**: User uploads corrupted CSV; system shows friendly error.
- [ ] **Date Format Handling**: System correctly parses DD/MM/YYYY vs MM/DD/YYYY based on settings.
- [ ] **Multi-page PDF**: System parses PDF statement spanning 3 pages.
- [ ] **Ignored Lines**: System ignores "Opening Balance" and "Closing Balance" rows in CSV.
- [ ] **Currency Detection**: System detects USD currency in statement metadata.
- [ ] **Unknown Format**: User uploads unsupported bank format; system asks for mapping.
- [ ] **Map Columns**: User manually maps "Trans Date", "Debit", "Credit" columns for new CSV.
- [ ] **Preview Parsing**: User previews parsed data before confirming import.
- [ ] **Cancel Import**: User cancels import after previewing errors.
- [ ] **Partial Success**: System imports 98 records, flags 2 for review (ambiguous).
- [ ] **Large File**: User uploads 5MB CSV (5000 rows); system processes async.
- [ ] **Encoding Handling**: System correctly handles UTF-8 chars in merchant names (e.g., café).
- [ ] **Negative Values**: System handles "-$50.00" as outflow correctly.
- [ ] **Positive Outflows**: System handles "(50.00)" format as outflow.
- [ ] **Description Cleaning**: System trims whitespace and "CARD TRANS" prefixes.
- [ ] **Delete Import**: User deletes an entire imported batch (cascades to raw lines).

### Phase 4: Reconciliation Engine (51-75)
- [ ] **Auto-Match Exact**: System auto-matches import ($50, 1/1) with manual entry ($50, 1/1).
- [ ] **Auto-Match Near Date**: System matches import ($50, 1/2) with manual entry ($50, 1/1) (Score > 85).
- [ ] **Manual Match Suggestion**: System suggests pairing import ($50) with entry ($50) despite 4-day gap.
- [ ] **Create from Statement (Simple)**: User clicks "Create" on unmatched import; pre-fills date/amount.
- [ ] **Create from Statement (Rule)**: "Netflix" import auto-categorizes to "Subscriptions" via rule.
- [ ] **One-to-Many Match**: User matches 1 bank withdrawal ($100) to 2 manual expense entries ($40 + $60).
- [ ] **Many-to-One Match**: User matches 2 bank charges ($10 + $0.50 fee) to 1 manual entry ($10.50).
- [ ] **Bank Fee Adjustment**: User accepts match with $0.10 difference; system creates "Bank Fee" entry.
- [ ] **FX Variance Adjustment**: User matches USD import to SGD entry; system calculates FX Gain/Loss.
- [ ] **Unmatch**: User detaches a reconciled link; status reverts to "Pending".
- [ ] **Bulk Accept**: User selects 10 "High Confidence" matches and accepts all.
- [ ] **Ignore Transaction**: User marks a "Bank Error" line as "Ignored" (excludes from recon).
- [ ] **Reconcile Period**: User "Locks" reconciliation up to Jan 31st.
- [ ] **Modify Reconciled Entry**: User tries to edit amount of reconciled entry -> **Blocked/Warning**.
- [ ] **Void Reconciled Entry**: User voids reconciled entry; system warns to unmatch first.
- [x] **Recon Progress Bar**: User sees "85% Reconciled" for Jan statement. *(test_core_journeys.py::test_reconciliation_stats)*
- [ ] **Filter Unreconciled**: User filters view to show only unmatched manual entries.
- [ ] **Search Statement**: User searches "Starbucks" in statement lines.
- [ ] **Review Low Confidence**: User reviews a 60% match score (wrong date?) and rejects it.
- [ ] **Rule Creation**: User creates "If description contains 'Uber', set category 'Transport'".
- [ ] **Rule Application**: System applies new rule to existing unmatched history.
- [ ] **Rule Conflict**: System picks specific rule ("Uber Eats" -> Food) over generic ("Uber" -> Transport).
- [ ] **Cross-Month Match**: Matching Jan 31 transaction with Feb 1st bank clear.
- [ ] **Duplicate Warning**: System warns if user tries to link import to already linked entry.
- [ ] **Force Match**: User manually links two totally different records (Admin override).

### Phase 5: Reporting & Visualization (76-90)
- [x] **View Balance Sheet**: User views BS as of today; sees Assets = Liab + Equity. *(test_core_journeys.py::test_balance_sheet_report)*
- [x] **View Income Statement**: User views P&L for "Last Month". *(test_core_journeys.py::test_income_statement_report)*
- [ ] **Drill Down**: User clicks "Food" in P&L -> sees list of food transactions.
- [ ] **Trend Analysis**: User views "6 Month Expense Trend" bar chart.
- [ ] **Category Pie Chart**: User sees "Where my money went" breakdown.
- [ ] **Net Worth Tracking**: User views line chart of Net Worth over 1 year.
- [ ] **Savings Rate**: System calculates (Income - Expense) / Income %.
- [x] **Cash Flow Report**: User views Operating vs Investing vs Financing flows. *(test_core_journeys.py::test_cash_flow_report)*
- [ ] **Multi-currency Report**: User views BS in SGD (USD assets converted at closing rate).
- [ ] **Export PDF**: User downloads P&L as PDF.
- [ ] **Export CSV**: User downloads raw transaction list for Excel.
- [ ] **Filter by Tag**: User generates report for tag "#Holiday2025".
- [ ] **Compare Periods**: User compares Jan 2026 vs Dec 2025.
- [ ] **Unrealized Gains**: User views report showing FX impact on USD accounts.
- [ ] **Missing Data Warning**: Report warns "Jan 2026 not fully reconciled".

### Phase 6: AI Advisor & Smart Features (91-100)
- [ ] **Ask Balance**: User asks "How much cash do I have?"; AI queries BS.
- [ ] **Ask Spending**: User asks "How much did I spend on food?"; AI queries P&L.
- [ ] **Spending Insight**: AI suggests "Your food spend is 20% higher than last month."
- [ ] **Anomaly Detection**: AI alerts "Duplicate subscription detected?".
- [ ] **Categorization Help**: AI suggests "Expenses:Software" for "Github" transaction.
- [ ] **Budget Advice**: User asks "Can I afford a PS5?"; AI checks Free Cash Flow.
- [ ] **Investment Check**: User asks "What is my asset allocation?"; AI summarizes.
- [ ] **Privacy Guard**: User asks AI for full account number; AI refuses (Redacted).
- [ ] **Context History**: User asks "What about last month?" (follows up on previous Q).
- [ ] **Disclaimer**: AI response includes "Not financial advice" footer.

---

## 4. Implementation Notes

### 4.1 Tools
- **Backend**: `pytest` for Integration/Unit.
- **Frontend/E2E**: `Playwright` (TypeScript).
- **Smoke**: Custom Python script or simple `curl`/`httpie` sequence.
- **Test Data**: `tools/generate_pdf_fixtures.py` (ReportLab) for generating PDF inputs.

### 4.2 CI/CD Integration
- **PR Check**: Run Unit + Integration + Phase 1-3 E2E subset.
- **Staging Deploy**: Run Full E2E (All 100 scenarios if feasible, or critical 50).
- **Prod Deploy**: Run Smoke Tests (Read-only).

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/e2e/` and `tools/smoke_test.sh`
>
> ℹ️ **Non-contiguous AC numbering**: Gaps in `AC8.x.y` numbers within `docs/infra_registry.yaml` reflect deprecated/merged ACs preserved for historical traceability. Do **not** renumber. New ACs append to the next available index in the relevant feature block.

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
| AC8.13.17 | AC registry generation preserves canonical descriptions and stores entries under ACx.y merge anchors without committed totals | `test_main_appends_missing_ac_without_rewriting_existing_registry` / `test_AC8_13_17_ac_traceability_runs_registry_generation_check` | `tests/tooling/test_generate_ac_registry.py` / `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
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

**Traceability Ownership**:
- This table owns the intended AC-to-proof mapping for EPIC-008.
- Current AC counts, covered/untested totals, and placeholder/stub exclusions are
  owned by [the generated coverage report](../analysis/test-ac-coverage-report.md)
  and `python tools/analyze_test_ac_coverage.py --no-write --stdout`.
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

### 5.1 E2E Test Files

| File | Role | AC Ownership |
|------|------|--------------|
| `apps/backend/tests/e2e/test_core_journeys.py` | Backend Tier 1 scenario/API coverage | AC8.1-AC8.10 |
| `apps/backend/tests/e2e/test_auth_flows.py` | Backend auth flow coverage | AC8.2, AC8.7 |
| `apps/backend/tests/e2e/test_e2e_flows.py` | Backend report/navigation flow coverage | AC8.2, AC8.6 |
| `tests/e2e/test_statement_upload_e2e.py` | Statement upload readiness E2E | AC8.4.2, AC8.4.3 |
| `tests/e2e/test_statement_full_journey.py` | Full statement hard gate | AC8.13.1-AC8.13.8 |
| `tests/e2e/test_brokerage_upload_to_portfolio_value.py` | Brokerage portfolio hard gate | AC8.13.10, AC8.13.18, AC8.13.19 |
| `tests/e2e/test_vision_upload_to_dashboard_hard_gate.py` | Deterministic upload-to-dashboard hard gate | AC8.13.28-AC8.13.32 |
| `tests/e2e/test_personal_financial_report_package.py` | Personal financial report package post-merge proof | AC5.1.1, AC5.1.4, AC5.2.3, AC5.3.1, AC5.8.1, AC5.12.4, AC5.13.4, AC11.8.3, AC11.9.1, AC11.9.2, AC11.9.3, AC11.11.1, AC11.11.2, AC17.10.1, AC17.10.2 |
| `tests/e2e/test_four_asset_net_worth_golden_path.py` | Four-asset net-worth hard gate | AC8.13.42, AC8.13.10, AC5.7.3, AC11.9.1, AC11.9.2, AC11.9.3, AC17.5.4 |
| `tests/e2e/test_market_data_price_paths.py` | Provider-backed market-data price path gate | AC11.10.7, AC11.10.11 |
| `tests/e2e/test_production_readonly_smoke.py` | Production-safe read-only smoke | AC8.13.9 |
| `tests/e2e/test_core_journeys.py` | Supplemental post-merge API smoke | AC8.1, AC8.3, AC8.4, AC8.7, AC8.8, AC8.10, AC1.5, AC6.5, AC6.11 |
| `tests/e2e/test_e2e_flows.py` | Supplemental browser route/auth smoke | AC8.13.9, AC8.10.8, AC16.12.6, AC1.7.1 |
| `tests/e2e/test_auth_flows.py` | Supplemental frontend auth/API-path smoke | AC8.10.8, AC8.10.9, AC16.12.5, AC16.12.6, AC1.7.1 |
| `tests/e2e/test_version_check.py` | Deployment version smoke | AC8.13.36, AC8.13.39 |

Product E2E files under `tests/e2e/test_*.py` and
`apps/backend/tests/e2e/test_*.py` must carry AC references directly. They are
not eligible for `docs/analysis/traceability-exceptions.md`; only fixtures and
shared harness files such as `tests/e2e/conftest.py` may use that exception
path. The `repo/e2e_regressions/` tree belongs to the `repo/` infra2 submodule
and is managed by the infrastructure submodule sync process, not by
finance_report AC coverage.

### 5.2 Tier 1 Test -> AC Mapping (Complete)

| Test Function | ACs Covered | Description |
|---------------|-------------|-------------|
| `test_api_health_check` | AC8.1.1, AC8.8.1 | GET /health returns 200 |
| `test_create_cash_account` | AC8.2.2 | Create Wallet asset account |
| `test_create_bank_account` | AC8.2.3 | Create DBS Savings asset account |
| `test_update_account` | AC8.2.4 | Update account name |
| `test_delete_account` | AC8.2.5 | Delete account + verify 404 |
| `test_accounts_crud_api` | AC8.8.2 | Full CRUD: create/list/get/update |
| `test_simple_expense_entry` | AC8.3.1 | $5 coffee with Expense+Asset accounts |
| `test_void_journal_entry` | AC8.3.2 | Post then void with reason |
| `test_post_draft_entry` | AC8.3.3 | Draft → posted status transition |
| `test_unbalanced_journal_entry_rejection` | AC8.3.4 | 422 on unbalanced schema validation |
| `test_journal_entry_crud` | AC8.3.5, AC8.8.3 | Create/read/list/delete lifecycle |
| `test_reconciliation_engine_runs` | AC8.5.1, AC8.8.5 | POST /reconciliation/run |
| `test_reconciliation_stats` | AC8.5.2 | GET /reconciliation/stats |
| `test_balance_sheet_report` | AC8.6.1, AC8.8.4 | GET /reports/balance-sheet |
| `test_income_statement_report` | AC8.6.2 | GET /reports/income-statement with date params |
| `test_cash_flow_report` | AC8.6.3 | GET /reports/cash-flow with date params |
| `test_reports_currencies_endpoint` | AC8.6.1 (supp) | GET /reports/currencies |
| `test_api_authentication_failures` | AC8.7.1 | Login with invalid creds |
| `test_unauthorized_access_blocked` | AC8.7.2 | public_client hits 401 on 3 endpoints |
| `test_user_session_management` | AC8.7.3 | GET /auth/me returns user info |
| `test_register_and_login_flow` | AC8.2.1, AC8.7.1 (supp) | Register → Login via public_client |
| `test_backend_service_reachable` | AC8.1.2 | Backend health + version info |
| `test_frontend_api_proxy_reachable` | AC8.1.3 | Frontend API proxy connectivity |
| `test_database_connectivity` | AC8.1.4 | DB round-trip via account create |
| `test_statement_upload_csv` | AC8.4.1, AC8.10.4 | CSV statement upload → 202 accepted |
| `test_statement_list_and_get` | AC8.4.2 | List + get individual statement |
| `test_statement_full_flow` | AC8.4.3 | Upload → list → get → approve flow |
| `test_reconciliation_match_acceptance` | AC8.5.3 | Run recon + check matches/unmatched |
| `test_report_navigation_all_endpoints` | AC8.6.4 | All 4 report endpoints return 200 |
| `test_pr_workflow_runs_e2e_tests` | AC8.9.1 | pr-test.yml contains E2E step |
| `test_smoke_tests_integrated` | AC8.9.2 | smoke_test.sh exists and is executable |
| `test_critical_test_check_in_workflow` | AC8.9.3 | pr-test.yml references critical tests |
| `test_environment_isolation` | AC8.9.4 | pr-test.yml uses BRANCH_NAME isolation |
| `test_traceability_health_endpoint` | AC8.10.1 | Dedicated: GET /health |
| `test_traceability_user_can_create_account` | AC8.10.2 | Dedicated: POST /accounts |
| `test_traceability_user_can_create_journal_entry` | AC8.10.3 | Dedicated: POST /journal/entries |
| `test_traceability_reconciliation_engine` | AC8.10.5 | Dedicated: POST /reconciliation/run |
| `test_traceability_unbalanced_entry_rejected` | AC8.10.6 | Dedicated: 400 on unbalanced |
| `test_traceability_reports_api` | AC8.10.7 | Dedicated: GET /reports/balance-sheet |
| `test_traceability_user_registration` | AC8.10.8 | Dedicated: POST /auth/register |
| `test_traceability_authentication_validation` | AC8.10.9 | Dedicated: invalid login → 400/401 |

### 5.3 CI/CD Integration Status

- ✅ **PR Workflow**: `.github/workflows/pr-test.yml` runs E2E tests on every PR
- ✅ **Smoke Tests**: `tools/smoke_test.sh` integrated into PR pipeline
- ✅ **Critical Proof Check**: `tools/check_critical_proof_matrix.py` validates core proof matrix results
- ✅ **Environment Isolation**: Each PR gets isolated DB/Redis/MinIO via Dokploy

### 5.4 Known Gaps

0. **Personal Financial Report Package Post-Merge E2E**:
   - **Status**: ✅ Implemented under [#565](https://github.com/wangzitian0/finance_report/issues/565) with `test_personal_financial_report_package_post_merge_journey`
   - **Scope**: Fresh-user post-merge proof that generates one personal report package from trusted source data and verifies statements, schedules, notes, and source traceability.
   - **Proof**: `critical-proof-matrix.yaml` -> `personal-financial-report-package-post-merge`
   - **Execution contract**: Because the proof carries the `llm` marker, both `.github/workflows/staging-deploy.yml` and `.github/workflows/staging-ai-ocr-gate.yml` must include the personal financial report package test in the serialized AI/OCR gate command and audit inventory.
   - **Dependency sequence**:
     1. Foundation contract: [#570](https://github.com/wangzitian0/finance_report/issues/570)
     2. Package content inputs: [#564](https://github.com/wangzitian0/finance_report/issues/564), [#566](https://github.com/wangzitian0/finance_report/issues/566)
     3. Explanatory output layers: [#571](https://github.com/wangzitian0/finance_report/issues/571), [#572](https://github.com/wangzitian0/finance_report/issues/572)
     4. Representative fixture contract: [#573](https://github.com/wangzitian0/finance_report/issues/573)
   - **Prerequisite fixture**: [#573](https://github.com/wangzitian0/finance_report/issues/573) owns the representative fresh-user fixture contract: bank cash, income/expense activity, brokerage holdings, market prices, dividends, manual valuation, liability, restricted holdings, reviewed sources, exact expected totals, notes, and traceability anchors.
   - **Contract dependencies**: [#570](https://github.com/wangzitian0/finance_report/issues/570) owns section/API shape, [#571](https://github.com/wangzitian0/finance_report/issues/571) owns notes/disclosures, and [#572](https://github.com/wangzitian0/finance_report/issues/572) owns the traceability appendix.
   - **Closure rule**: Partial. `personal-financial-report-package` points to `personal-financial-report-package-post-merge` as its baseline proof, and remains `partial` in `docs/ssot/critical-proof-matrix.yaml` until #573 closes.

1. **Statement Upload Parsing** (`test_statement_upload_e2e.py`):
   - **Status**: ✅ Fixed (Tier 3 assertion now blocks immediate AI/OCR rejection)
   - **Change**: Test validates upload success, statement visibility, and rejects `status=rejected` as an AI/OCR readiness failure
   - **Note**: Full parsed transaction assertions live in `test_statement_full_journey.py`, the deploy-blocking hard gate
   - **Result**: Upload-only E2E can remain lightweight while still catching provider/config failure before full journey polling

2. **Full Statement Journey (Tier 3)** (`test_statement_full_journey.py`):
   - **Status**: Implemented hard gate — requires `APP_URL` pointing to a running frontend+backend
   - **Coverage**: AC8.13.1–5 (PDF upload, parse polling, transactions, approve, balance sheet)
   - **Hard-gate rule**: When `STRICT_E2E_GATES=true`, critical E2E skips are converted to failures; `status=rejected` fails instead of skips and reports the statement id, validation error, parsing progress, confidence, and selected model. The separate post-merge `Staging AI/OCR Gate` is the provider-backed AI/OCR gate.
   - **Provider budget rule**: Tests marked `llm` run serially in the AI/OCR gate, not under the staging deploy `-n 4` parallel phase. PR preview E2E excludes `llm` tests and does not inject `ZAI_API_KEY`, so automated GLM/OCR provider calls are centralized in the staging AI/OCR gate. Every critical `post_merge_environment` proof in `critical-proof-matrix.yaml` that carries `llm` must be listed in both `.github/workflows/staging-deploy.yml` and `.github/workflows/staging-ai-ocr-gate.yml`. Staging pins `PRIMARY_MODEL=glm-5.1`, `OCR_MODEL=glm-4.6v`, and `VISION_MODEL=glm-4.6v` for the AI/OCR gate. The gate waits for the same SHA's `CI` push run to succeed before spending provider quota.
   - **Fast-fail guardrail**: Staging post-merge workflows use GitHub concurrency without canceling a running validation. GitHub retains one running run and one latest pending run per group, so rapid pushes are batched to the latest pending commit rather than interrupting the active deploy/gate. The deploy-health job is capped at 75 minutes, the deploy E2E step is capped at 22 minutes, and phase timing logs identify smoke and core non-LLM E2E latency. Provider-backed OCR parsing runs afterward in the separate `Staging AI/OCR Gate`.
   - **Route diagnostics**: If staging `/api/health` remains 404, `tools/health_check.sh` probes `/api/ping` and `/` and identifies a likely Traefik API route miss or web-route shadow before failing the deploy.

3. **Multi-Brokerage Upload to Portfolio Value (Tier 3)** (`test_brokerage_upload_to_portfolio_value.py`):
   - **Status**: Implemented hard gate for Issue #404
   - **Coverage**: AC8.13.10 (Moomoo + Futu PDF upload, real OCR parse polling, parsed-statement position import, holdings visibility, balance-sheet asset value), AC8.13.18, AC8.13.19
   - **Path matrix**: The README `Core Proof Paths` section and the [EPIC-017 brokerage PDF to asset report proof matrix](EPIC-017.portfolio-management.md#brokerage-pdf-to-asset-report-proof-matrix) map this provider-backed gate to the backend and frontend proof rows.
   - **Failure diagnostics**: Assertions include statement IDs and response bodies for OCR rejection, import zero-counts, missing holdings, and reporting failures. Portfolio value coverage is checked against balance-sheet market valuation adjustment lines, not whole `total_assets`, so unrelated cash or bank lines cannot mask or falsely fail the imported portfolio valuation check. Failures include imported position count, holdings total market value, valuation adjustment total, non-portfolio asset total, total assets, net worth adjustment, and relevant asset lines.
   - **Provider budget rule**: Runs in the same serialized `Staging AI/OCR Gate` as the DBS full journey.

4. **Four-Asset As-of Net Worth Golden Path (Tier 3)** (`test_four_asset_net_worth_golden_path.py`):
   - **Status**: Implemented hard gate for Issue #444
   - **Coverage**: AC8.13.42 proves one fresh-user path across bank cash, brokerage PDF positions, property value, mortgage liability, and ESOP restricted equity. The test completes explicit upload, Stage 1 approval/posting, Stage 2 reconciliation, brokerage import, manual valuation creation, exact Decimal-safe as-of balance-sheet totals, and dashboard/report total assertions.
   - **Provider budget rule**: Runs in the same serialized `Staging AI/OCR Gate` as the DBS and brokerage PDF hard gates because it imports a real brokerage PDF through the configured OCR path.

5. **Production Read-only E2E Smoke** (`test_production_readonly_smoke.py`):
   - **Status**: Implemented for production release
   - **Coverage**: Health payload, anonymous auth boundary, browser shell/login route, optional credential-gated dashboard
   - **Allowed skip**: Authenticated dashboard check may skip only when `PROD_SMOKE_EMAIL` / `PROD_SMOKE_PASSWORD` are not configured; it must not mutate production data

6. **Tier 2 (HTTP E2E)**: Not yet implemented. Would test against deployed PR environments.

7. **Scenario coverage tracking**: Section 3 remains a planning checklist.
   Current proof counts belong to generated reports and CI artifacts, not this
   prose list.

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

Useful content from `testing-implementation.md`, `testing-gap-analysis.md`,
`TEST-COVERAGE-PLAN.md`, and `AC-TEST-TRACEABILITY-AUDIT.md` was consolidated
before the archive snapshots were removed. The removed inventory is retained in
[#548](https://github.com/wangzitian0/finance_report/issues/548); current proof
is owned by the active README -> EPIC -> AC registry -> tests -> CI artifact
chain:

- The durable testing assets are factories, performance/load-test entry points,
  Playwright E2E scaffolding, Moon task integration, and critical-path smoke
  gates.
- Historical coverage numbers in the archive are superseded by
  `docs/analysis/test-ac-coverage-report.md`, `unified-coverage.json`, and
  `common/coverage/policy.py`.
- Historical AC traceability snapshots are superseded by the generated
  `ac-test-traceability-audit` CI artifact.
- The business-critical service focus remains valid: reporting,
  reconciliation, FX revaluation, assets, review queue, processing account,
  accounting, and validation.
- Skipped Tier 2/3 tests and placeholder assertions do not count as proof under
  the current policy; the CI traceability gate fails missing, placeholder-only,
  and stub-only mandatory AC references. Manual-verification treatment remains
  tracked by [#454](https://github.com/wangzitian0/finance_report/issues/454).

### 6.1 Archive Residual Backlog Ownership

The removed testing archive also contained future testing-capability ideas. They
are not current CI requirements, but they are owned here so they do not remain
archive-only TODOs:

| Residual | Owner AC | Current status | Future proof boundary |
|---|---|---|---|
| Visual regression | AC8.13.61 | P3 future testing capability; no current CI gate | Add a Playwright screenshot or equivalent visual regression gate only when visual stability becomes a release requirement |
| Test observability: test report dashboard, failure notification, trend analysis | AC8.13.62 | Current replacements are GitHub Step Summary, CI artifacts, Coveralls, and generated coverage reports | Add report dashboard, Slack/Email failure notification, or failure-rate trend analysis only as explicit EPIC-008 work |
| Performance testing | AC8.13.63 | Locust exists for load tests and staging has a non-blocking API benchmark | Promote to a required P95 trend gate only after threshold ownership and failure policy are defined |

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [../analysis/test-ac-coverage-report.md](../analysis/test-ac-coverage-report.md) — generated AC coverage report.
- [../ssot/coverage.md](../ssot/coverage.md) — coverage policy semantics.
- [../ssot/ci-cd.md](../ssot/ci-cd.md) — CI gate semantics.
- [../ssot/env_smoke_test.md](../ssot/env_smoke_test.md) — environment smoke-test rationale and command semantics.
- [../../apps/backend/tests/README.md](../../apps/backend/tests/README.md) — backend test-suite navigation.

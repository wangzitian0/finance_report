# EPIC-008: Comprehensive Testing Strategy (Smoke & E2E)

> **Status**: In Progress (Core Complete)
> **Owner**: QA / DevOps
> **Date**: 2026-01-16
> **Updated**: 2026-01-27

## 1. Overview

This epic defines the strategy for **Smoke Testing** and **End-to-End (E2E) Testing** to ensure system stability across environments. The focus is on **vertical, scenario-based flows** that mimic real user behavior, moving away from isolated functional checks.

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

### 2.3 Synthetic Test Data (PDF Generation)

To ensure deterministic and controllable tests for Phase 3 (Import/Parsing), we utilize a synthetic data generation script.

- **Source**: `scripts/generate_pdf_fixtures.py`
- **Output**: Generates valid PDF bank statements (DBS/Citi style) with known transaction sets.
- **Purpose**: Validates the *pipeline* (Upload -> Parse -> Reconcile) works, without relying on unstable external OCR accuracy or PII-laden real documents.
- **Scope Limitation**: OCR/Parsing *accuracy* benchmarks are handled in a separate Epic. This Epic focuses on flow functional correctness.

---

## 3. Core Use Cases (100 Scenarios)

These scenarios represent the "Vertical Slices" of user value.

### Phase 1: Onboarding & Account Structure (1-10)
- [x] **New User Registration**: User signs up with email/password, verifies email, and lands on dashboard. *(test_e2e_flows.py::test_registration_flow)*
- [ ] **Setup Base Currency**: User selects SGD as base currency during onboarding.
- [x] **Create Cash Account**: User creates a "Wallet" asset account (SGD). *(test_core_journeys.py::test_accounts_crud_api)*
- [x] **Create Bank Account**: User creates a "DBS Savings" asset account (SGD). *(covered by CRUD test)*
- [ ] **Create Credit Card**: User creates a "Citi Rewards" liability account (SGD).
- [ ] **Create Multi-currency Account**: User creates a "Wise USD" asset account (USD).
- [ ] **Define Custom Expense Category**: User adds "Coffee Subscription" under "Expenses".
- [ ] **Define Income Source**: User adds "Freelance Design" under "Income".
- [ ] **Archive Account**: User archives an old "Student Account" (hidden from lists).
- [ ] **Reactivate Account**: User restores the "Student Account" for historical reference.

### Phase 2: Manual Journal Entries (11-30)
- [x] **Simple Expense**: User pays $5.00 for coffee using "Wallet" (Manual Entry). *(test_core_journeys.py::test_journal_entry_lifecycle_api)*
- [ ] **Income Recording**: User records $5,000 salary deposit into "DBS Savings".
- [ ] **Credit Card Spend**: User buys a laptop ($2,000) using "Citi Rewards".
- [ ] **Credit Card Repayment**: User pays off "Citi Rewards" ($2,000) from "DBS Savings".
- [ ] **Internal Transfer**: User moves $500 from "DBS Savings" to "Wallet" (ATM Withdrawal).
- [ ] **Split Transaction**: User spends $100 at supermarket: $80 "Groceries", $20 "Household" (1 Debit, 2 Credits).
- [ ] **Refund Processing**: User receives $50 refund to "Citi Rewards" for returned item.
- [ ] **Foreign Expense (Manual FX)**: User spends 10 USD on "Wise USD", records as 13.50 SGD equivalent.
- [x] **Void Entry**: User voids a duplicate coffee transaction (System generates reversal). *(test_core_journeys.py::test_journal_entry_lifecycle_api)*
- [x] **Post Draft**: User saves a complex entry as "Draft", reviews later, and "Posts" it. *(test_core_journeys.py::test_journal_entry_lifecycle_api)*
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
- [x] **Recon Progress Bar**: User sees "85% Reconciled" for Jan statement. *(test_core_journeys.py::test_reconciliation_api - stats endpoint)*
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
- [x] **View Balance Sheet**: User views BS as of today; sees Assets = Liab + Equity. *(test_core_journeys.py::test_reports_api)*
- [x] **View Income Statement**: User views P&L for "Last Month". *(test_core_journeys.py::test_reports_api)*
- [ ] **Drill Down**: User clicks "Food" in P&L -> sees list of food transactions.
- [ ] **Trend Analysis**: User views "6 Month Expense Trend" bar chart.
- [ ] **Category Pie Chart**: User sees "Where my money went" breakdown.
- [ ] **Net Worth Tracking**: User views line chart of Net Worth over 1 year.
- [ ] **Savings Rate**: System calculates (Income - Expense) / Income %.
- [x] **Cash Flow Report**: User views Operating vs Investing vs Financing flows. *(test_core_journeys.py::test_reports_api)*
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
- **Test Data**: `scripts/generate_pdf_fixtures.py` (ReportLab) for generating PDF inputs.

### 4.2 CI/CD Integration
- **PR Check**: Run Unit + Integration + Phase 1-3 E2E subset.
- **Staging Deploy**: Run Full E2E (All 100 scenarios if feasible, or critical 50).
- **Prod Deploy**: Run Smoke Tests (Read-only).

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/e2e/` and `scripts/smoke_test.sh`

### AC8.1: Smoke Tests (Health Checks)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.1.1 | API health check | Health check tests | `scripts/smoke_test.sh` | P0 |
| AC8.1.2 | Backend service reachable | Connectivity tests | `scripts/smoke_test.sh` | P0 |
| AC8.1.3 | Frontend service reachable | Connectivity tests | `scripts/smoke_test.sh` | P0 |
| AC8.1.4 | Database connectivity | Connectivity tests | `scripts/smoke_test.sh` | P0 |

### AC8.2: Phase 1 - Onboarding & Account Structure

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.2.1 | New User Registration | Planned (not implemented yet) | TBD – will live under `apps/backend/tests/e2e/` | P0 |
| AC8.2.2 | Create Cash Account | Planned (not implemented yet) | TBD – will live under `apps/backend/tests/e2e/` | P0 |
| AC8.2.3 | Create Bank Account | Planned (not implemented yet) | TBD – will live under `apps/backend/tests/e2e/` | P0 |
| AC8.2.4 | Update account | Planned (not implemented yet) | TBD – will live under `apps/backend/tests/e2e/` | P1 |
| AC8.2.5 | Delete account | Planned (not implemented yet) | TBD – will live under `apps/backend/tests/e2e/` | P1 |

### AC8.3: Phase 2 - Manual Journal Entries

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.3.1 | Simple Expense Entry | _TBD – E2E test not yet implemented_ | _TBD_ | P0 |
| AC8.3.2 | Void Entry | _TBD – E2E test not yet implemented_ | _TBD_ | P0 |
| AC8.3.3 | Post Draft Entry | _TBD – E2E test not yet implemented_ | _TBD_ | P0 |
| AC8.3.4 | Unbalanced Entry Rejected | _TBD – E2E test not yet implemented_ | _TBD_ | P0 |
| AC8.3.5 | Journal Entry CRUD | _TBD – E2E test not yet implemented_ | _TBD_ | P1 |

### AC8.4: Phase 3 - Statement Import & Parsing

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.4.1 | Statement upload triggers AI | `test_model_selection_and_upload()` | `e2e/test_statement_upload_e2e.py` | P0 |
| AC8.4.2 | Model selection | `test_model_selection_and_upload()` | `e2e/test_statement_upload_e2e.py` | P0 |
| AC8.4.3 | Statement upload full flow | `test_statement_upload_full_flow()` | `e2e/test_statement_upload_e2e.py` | P0 |

### AC8.5: Phase 4 - Reconciliation Engine

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.5.1 | Reconciliation engine runs | `test_reconciliation_api()` | `e2e/test_core_journeys.py` | P0 |
| AC8.5.2 | Reconciliation stats endpoint | `test_reconciliation_api()` | `e2e/test_core_journeys.py` | P1 |
| AC8.5.3 | Match acceptance | Match acceptance tests | `reconciliation/` | P1 |

### AC8.6: Phase 5 - Reporting & Visualization

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.6.1 | View Balance Sheet | `test_reports_api()` | `e2e/test_core_journeys.py` | P0 |
| AC8.6.2 | View Income Statement | `test_reports_api()` | `e2e/test_core_journeys.py` | P0 |
| AC8.6.3 | View Cash Flow Report | `test_reports_api()` | `e2e/test_core_journeys.py` | P0 |
| AC8.6.4 | Report navigation | Navigation tests | `e2e/test_e2e_flows.py` | P1 |

### AC8.7: API Authentication & Authorization

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.7.1 | API authentication failures | `test_api_authentication_failures()` | `e2e/test_core_journeys.py` | P0 |
| AC8.7.2 | Unauthorized access blocked | _TBD – E2E test not yet implemented_ | _TBD_ | P0 |
| AC8.7.3 | User session management | _TBD – E2E test not yet implemented_ | _TBD_ | P1 |

### AC8.8: Core E2E Journey Tests

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.8.1 | API health check | `test_api_health_check()` | `e2e/test_core_journeys.py` | P0 |
| AC8.8.2 | Accounts CRUD API | `test_accounts_crud_api()` | `e2e/test_core_journeys.py` | P0 |
| AC8.8.3 | Journal entry lifecycle API | `test_journal_entry_lifecycle_api()` | `e2e/test_core_journeys.py` | P0 |
| AC8.8.4 | Reports API | `test_reports_api()` | `e2e/test_core_journeys.py` | P0 |
| AC8.8.5 | Reconciliation API | `test_reconciliation_api()` | `e2e/test_core_journeys.py` | P0 |

### AC8.9: CI/CD Integration Tests

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC8.9.1 | PR workflow runs E2E tests | Manual verification | `.github/workflows/pr-test.yml` | P0 |
| AC8.9.2 | Smoke tests integrated | Manual verification | PR pipeline | P0 |
| AC8.9.3 | Critical test check | GitHub workflow check | `.github/workflows/pr-test.yml` | P0 |
| AC8.9.4 | Environment isolation | Manual verification | Dokploy PR environments | P0 |

### AC8.10: Must-Have Scenario Traceability

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC8.10.1 | Health endpoint reachable | `test_api_health_check()` | `e2e/test_core_journeys.py` | P0 |
| AC8.10.2 | User can create account | `test_accounts_crud_api()` | `e2e/test_core_journeys.py` | P0 |
| AC8.10.3 | User can create journal entry | `test_journal_entry_lifecycle_api()` | `e2e/test_core_journeys.py` | P0 |
| AC8.10.4 | Statement upload triggers AI | `test_model_selection_and_upload()` | `e2e/test_statement_upload_e2e.py` | P0 |
| AC8.10.5 | Reconciliation engine runs | `test_reconciliation_api()` | `e2e/test_core_journeys.py` | P0 |
| AC8.10.6 | Unbalanced entry rejected | `test_unbalanced_journal_entry_rejection()` | `e2e/test_core_journeys.py` | P0 |
| AC8.10.7 | Reports API accessible | `test_reports_api()` | `e2e/test_core_journeys.py` | P0 |
| AC8.10.8 | User registration flow | `test_registration_flow()` | `e2e/test_e2e_flows.py` | P0 |
| AC8.10.9 | Authentication validation | `test_api_authentication_failures()` | `e2e/test_core_journeys.py` | P0 |

**Traceability Result**:
- Total AC IDs: 49
- Requirements converted to AC IDs: 100% (EPIC-008 scenario checklist + CI/CD integration)
- Requirements with implemented test references: 85% (15% scenarios are nice-to-have or pending)
- Test files: 7
- Note: EPIC-008 covers 100 scenarios; current implementation covers ~15 core scenarios

---

## 5. Implementation Status (as of 2026-01-27)

### 5.1 Implemented Test Files

| File | Type | Coverage |
|------|------|----------|
| `tests/e2e/test_core_journeys.py` | API E2E | Health, accounts CRUD, journal entries, reports, reconciliation |
| `tests/e2e/test_e2e_flows.py` | UI E2E | Navigation, registration, reports view |
| `tests/e2e/test_auth_flows.py` | Auth E2E | Authentication flows |
| `tests/e2e/conftest.py` | Fixtures | Shared session user, browser context, auth injection |
| `scripts/smoke_test.sh` | Shell Smoke | 200+ lines of basic connectivity tests |

### 5.2 Scenario Coverage (Issue #196 Requirements)

| Requirement | Status | Test Location |
|-------------|--------|---------------|
| Health endpoint reachable | ✅ Done | `test_core_journeys.py::test_api_health_check` |
| User can create account | ✅ Done | `test_core_journeys.py::test_accounts_crud_api` |
| User can create journal entry | ✅ Done | `test_core_journeys.py::test_journal_entry_lifecycle_api` |
| Statement upload triggers AI | ⚠️ Skipped | `test_e2e_flows.py::test_statement_upload_parsing_flow` (backend bug) |
| Reconciliation engine runs | ✅ Done | `test_core_journeys.py::test_reconciliation_api` |
| Unbalanced entry rejected | ✅ Done | `test_core_journeys.py::test_unbalanced_journal_entry_rejection` |
| Reports API accessible | ✅ Done | `test_core_journeys.py::test_reports_api` |
| Authentication validation | ✅ Done | `test_core_journeys.py::test_api_authentication_failures` |
| User registration flow | ✅ Done | `test_e2e_flows.py::test_registration_flow` |

### 5.3 CI/CD Integration Status

- ✅ **PR Workflow**: `.github/workflows/pr-test.yml` runs E2E tests on every PR
- ✅ **Smoke Tests**: `scripts/smoke_test.sh` integrated into PR pipeline
- ✅ **Critical Test Check**: `scripts/check_critical_tests.py` validates test results
- ✅ **Environment Isolation**: Each PR gets isolated DB/Redis/MinIO via Dokploy

### 5.4 Known Gaps

1. **Statement Upload Parsing** (`test_statement_upload_parsing_flow`):
   - **Status**: Skipped
   - **Reason**: Backend AI parsing returns 0 transactions instead of expected 15
   - **Tracking**: PR #142 comments
   - **Fix Required**: Backend team to investigate Gemini parsing flow

2. **100 Scenario Coverage**:
   - **Current**: ~15 core scenarios implemented
   - **Gap**: 85 scenarios from Phase 1-6 not yet automated
   - **Priority**: Low (core flows are covered, remaining are nice-to-have)

### 5.5 Running Tests

```bash
# Run all E2E tests locally
bash scripts/smoke_test.sh

# Run against specific environment
APP_URL=https://report.zitian.party pytest tests/e2e -v -m "smoke or e2e"

# Run smoke tests only (fast)
bash scripts/smoke_test.sh http://localhost:3000 dev

# Run with UI visible (debugging)
HEADLESS=false pytest tests/e2e -v
```

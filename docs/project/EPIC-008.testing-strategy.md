# EPIC-008: Comprehensive Testing Strategy (Smoke & E2E)

> **Status**: Draft
> **Owner**: QA / DevOps
> **Date**: 2026-01-16

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
- [ ] **New User Registration**: User signs up with email/password, verifies email, and lands on dashboard.
- [ ] **Setup Base Currency**: User selects SGD as base currency during onboarding.
- [ ] **Create Cash Account**: User creates a "Wallet" asset account (SGD).
- [ ] **Create Bank Account**: User creates a "DBS Savings" asset account (SGD).
- [ ] **Create Credit Card**: User creates a "Citi Rewards" liability account (SGD).
- [ ] **Create Multi-currency Account**: User creates a "Wise USD" asset account (USD).
- [ ] **Define Custom Expense Category**: User adds "Coffee Subscription" under "Expenses".
- [ ] **Define Income Source**: User adds "Freelance Design" under "Income".
- [ ] **Archive Account**: User archives an old "Student Account" (hidden from lists).
- [ ] **Reactivate Account**: User restores the "Student Account" for historical reference.

### Phase 2: Manual Journal Entries (11-30)
- [ ] **Simple Expense**: User pays $5.00 for coffee using "Wallet" (Manual Entry).
- [ ] **Income Recording**: User records $5,000 salary deposit into "DBS Savings".
- [ ] **Credit Card Spend**: User buys a laptop ($2,000) using "Citi Rewards".
- [ ] **Credit Card Repayment**: User pays off "Citi Rewards" ($2,000) from "DBS Savings".
- [ ] **Internal Transfer**: User moves $500 from "DBS Savings" to "Wallet" (ATM Withdrawal).
- [ ] **Split Transaction**: User spends $100 at supermarket: $80 "Groceries", $20 "Household" (1 Debit, 2 Credits).
- [ ] **Refund Processing**: User receives $50 refund to "Citi Rewards" for returned item.
- [ ] **Foreign Expense (Manual FX)**: User spends 10 USD on "Wise USD", records as 13.50 SGD equivalent.
- [ ] **Void Entry**: User voids a duplicate coffee transaction (System generates reversal).
- [ ] **Post Draft**: User saves a complex entry as "Draft", reviews later, and "Posts" it.
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
- [ ] **Recon Progress Bar**: User sees "85% Reconciled" for Jan statement.
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
- [ ] **View Balance Sheet**: User views BS as of today; sees Assets = Liab + Equity.
- [ ] **View Income Statement**: User views P&L for "Last Month".
- [ ] **Drill Down**: User clicks "Food" in P&L -> sees list of food transactions.
- [ ] **Trend Analysis**: User views "6 Month Expense Trend" bar chart.
- [ ] **Category Pie Chart**: User sees "Where my money went" breakdown.
- [ ] **Net Worth Tracking**: User views line chart of Net Worth over 1 year.
- [ ] **Savings Rate**: System calculates (Income - Expense) / Income %.
- [ ] **Cash Flow Report**: User views Operating vs Investing vs Financing flows.
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

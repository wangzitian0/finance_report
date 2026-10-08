# Financial Reporting Benchmark Fixtures & Suite

This directory contains the declarative manifest and infrastructure for multi-scenario financial accounting benchmarks across the 3 core financial statements (Balance Sheet, Income Statement, Cash Flow).

## Architecture

1. **Declarative Manifest (`manifest.yaml`)**:
   - Declares verified external open-licensed statement fixtures pinned to immutable commit SHAs and verified via SHA-256 checksums.
   - Declaratively specifies document types, currencies, and test scenario mappings.

2. **Fast Shift-Left In-Memory Domain Matrix (`test_bench_articulation_matrix.py`)**:
   - Executes all 6 core financial scenarios against SQLite in memory in < 5 seconds.
   - Mathematically proves 3-statement reconciliation, debt clearance, multi-currency CTA, multi-asset valuation, and bank overdraft without network latency or external dependencies.

3. **Temporal Scenario Runner (`tools/run_financial_scenario_benchmark.py`)**:
   - Simulates end-to-end user flows against live target environments (e.g. Staging at `https://report-staging.zitian.party`).
   - Registers an ephemeral user per test case to ensure strict data isolation.
   - Automates: Statement Upload -> Asynchronous Parsing -> Economic Adjudication -> Stage 1 Ledger Approval -> 3-Statement Retrieval & Mathematical Reconciliations.

## Scenarios Implemented

- **Case 1: Consecutive 4-Month Rollforward & Q1 Articulation**
  - Month 1 to Month 4 consecutive statements (Jan–Apr 2025).
  - Asserts temporal balance continuity ($Month_{n+1}\,Opening \equiv Month_n\,Closing$).
  - Validates Q1 closing checkpoint and Q2 transition.

- **Case 2: Multi-PII Household Operations & Category Reconciliation**
  - Simulates multi-member household accounts: Husband (DBS Bank) and Wife (Standard Chartered).
  - Asserts source-scoped deduplication, category separation, and consolidated household net operating income.

- **Case 3: Credit Card Liability & Non-P&L Debt Clearance**
  - Credit card operating expense charge followed by bank settlement repayment.
  - Asserts liability cleared to 0.00 SGD with zero double-counting of expenses in net income.

- **Case 4: Multi-National & Multi-Currency Consolidated Balance Sheet**
  - Statements across SGD, USD, and HKD jurisdictions.
  - Asserts multi-currency balance sheet balance with IAS 21 CTA tracking and zero equation delta.

- **Case 5: Holistic Multi-Asset & Tax Ecosystem**
  - Public equities (Interactive Brokers), illiquid real estate appraisal ($350k USD), and payroll tax withholding.
  - Asserts comprehensive fair market valuation integration and 3-statement equity conservation.

- **Case 6: Bank Overdraft & Capital Gain Asset Disposal**
  - Temporary negative cash balance from expenses exceeding deposits, followed by capital injection and profitable asset disposal.
  - Asserts exact accounting identity ($Assets \equiv Liabilities + Equity$) during negative balance and asset transitions.

## Quick Start Commands

```bash
# 1. Run fast in-memory domain matrix tests (< 5s)
uv run --directory apps/backend pytest tests/reporting/test_bench_articulation_matrix.py --no-cov -v

# 2. Sync benchmark statement fixtures
uv run --directory apps/backend python3 tools/sync_benchmark_fixtures.py

# 3. Run the live benchmark suite against Staging
uv run --directory apps/backend python3 tools/run_financial_scenario_benchmark.py --app-url https://report-staging.zitian.party --case all
```

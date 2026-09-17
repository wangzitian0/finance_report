# Financial Reporting Benchmark Fixtures & Suite

This directory contains the declarative manifest and infrastructure for multi-scenario financial accounting benchmarks across the 3 core financial statements (Balance Sheet, Income Statement, Cash Flow).

## Architecture

1. **Declarative Manifest (`manifest.yaml`)**:
   - Declares external open-licensed statement PDFs (from DocuBench, Bankstatemently, etc.).
   - Pinned to upstream commit SHAs and verified via SHA-256 checksums.
   - Large raw PDFs (e.g. Fidelity Brokerage > 10MB) are automatically sliced on download to satisfy the 10MB upload gate without losing accounting fidelity.

2. **Fixture Sync Tool (`tools/sync_benchmark_fixtures.py`)**:
   - Sparse download tool: fetches external files on demand without cloning multi-gigabyte repos.
   - Verification flag: `--verify` checks local presence and SHA-256 integrity.

3. **Temporal Scenario Runner (`tools/run_financial_scenario_benchmark.py`)**:
   - Simulates real user flows against live target environments (e.g. Staging at `https://report-staging.zitian.party`).
   - Registers an ephemeral user per test case to ensure strict data isolation.
   - Automates: Statement Upload -> Asynchronous OCR/AI Parsing -> Economic Adjudication -> Stage 1 Ledger Approval -> 3-Statement Retrieval & Mathematical Reconciliations.

## Scenarios Implemented

- **Case 1: Consecutive Monthly Rollforward (连续双月滚续)**
  - Month 1: Jan 2025 Straits Capital Bank Statement (Opening: 15,450.75 SGD, Closing: 15,271.23 SGD, Net: -179.52 SGD).
  - Month 2: Feb 2025 Chained Statement (Opening: 15,271.23 SGD, Closing: 18,250.00 SGD, Net: +2,978.77 SGD).
  - Mathematical Assertions:
    - Balance chain continuity (M2 Opening == M1 Closing).
    - Balance Sheet equation delta == 0.00 (`Assets == Liabilities + Equity`).
    - Retained Earnings / Net Income accumulates across periods: `-179.52 + 2978.77 == 2799.25`.
    - Cash Flow identity: `Beginning Cash (15450.75) + Net Cash Flow (2799.25) == Ending Cash (18250.00)`.

- **Case 3: Bank-Brokerage Transfer & Asset Swap (银证划转不污染损益)**
  - Bank Statement: Initial 20,000.00 SGD, Transfer Out 5,000.00 SGD to Brokerage.
  - Brokerage Counter Asset Account: Receives 5,000.00 SGD.
  - Mathematical Assertions:
    - Zero P&L contamination: `Total Income == 0.00`, `Total Expenses == 0.00`, `Net Income == 0.00`.
    - Balance Sheet conservation: Total Assets = Bank Cash (15,000.00) + Brokerage Portfolio (5,000.00) = 20,000.00 SGD == Total Equity (20,000.00 SGD).
    - `equation_delta == 0.00`.

## Quick Start Commands

```bash
# 1. Sync & verify benchmark statement fixtures
uv run --directory apps/backend python3 tools/sync_benchmark_fixtures.py

# 2. Run the benchmark suite against Staging
uv run --directory apps/backend python3 tools/run_financial_scenario_benchmark.py --app-url https://report-staging.zitian.party --case 1,3
```

# Financial Reporting Benchmark Observatory

Continuous 3-statement financial reconciliation and accounting invariant tracking across tagged releases and staging deployments.

<div class="admonition tip" style="padding: 16px; margin: 16px 0; border-left: 4px solid #10b981; background: rgba(16, 185, 129, 0.08); border-radius: 4px;">
<p class="admonition-title" style="font-weight: bold; margin-bottom: 8px;">📊 Interactive Observatory Dashboard</p>
<p>
Access the standalone historical benchmark dashboard with interactive SVG latency and balance trendlines:
<br><br>
<a href="../benchmarks/index.html" class="md-button md-button--primary" style="background-color: #3f51b5; color: white; padding: 8px 16px; border-radius: 4px; text-decoration: none; font-weight: 600;">
Open Benchmark Observatory Dashboard →
</a>
</p>
</div>

---

## 🛡️ Monitored Financial Invariants (The Proof)

Each benchmark run executes multi-period accounting scenarios against the live application and mathematically asserts five core accounting identities:

| Invariant | Mathematical Formulation | Acceptance Criteria |
| :--- | :--- | :--- |
| **Balance Sheet Identity** | $Assets \equiv Liabilities + Equity + Cumulative\,Net\,Income$ | Exact equality ($\Delta = 0.00$ SGD) across all reporting periods. |
| **Temporal Multi-Period Rollforward** | $Month_{n+1}\,Opening\,Cash \equiv Month_n\,Closing\,Cash$ | Exact continuity without temporal drift or leakage across 4 consecutive months. |
| **Asset Reallocation / Internal Transfer** | $\Delta Revenue = 0.00, \Delta Expense = 0.00, \Delta Net\,Income = 0.00$ | Zero P&L contamination when swapping assets (e.g. Bank $\to$ Brokerage). |
| **Retained Earnings Articulation** | $Closing\,Equity = Opening\,Equity + Net\,Income$ | Net income articulates directly into balance sheet retained earnings. |
| **Cash Flow Conservation** | $Beginning\,Cash + Net\,Cash\,Flow \equiv Ending\,Cash$ | Direct and indirect reconciliation equality. |
| **Multi-Currency Consolidation** | $Assets_{base} \equiv \sum (Assets_i \times FX_i)$ | Consolidated balance sheet balances with $\Delta = 0.00$ across base and foreign currencies. |
| **Fair Market Valuation Integration** | $Assets_{securities} \equiv Holdings \times Price_{as\_of}$ | Portfolio positions reconcile and market adjustments reflect in Net Worth Adjustment. |

---

## 🧪 V2 Benchmark Scenarios Suite

The V2 benchmark test matrix covers end-to-end multi-period accounting sufficiency:

1. **Case 1: Consecutive 4-Month Rollforward & Q1 Articulation**
   Chains 4 consecutive monthly statements (Jan 2025 Straits Capital PDF, Feb/Mar/Apr 2025 chained Standard Chartered PDFs). Validates $Month_{n+1} \equiv Month_n$, Q1 closing checkpoint ($Net\,Income = +5,849.25$ SGD, $Assets = 21,300.00$ SGD), and Month 4 transition into Q2 ($Net\,Income = +8,749.25$ SGD, $Assets = 24,200.00$ SGD).
2. **Case 2: Standard Operations CSV Statement Flow & Category Reconciliation**
   Simulates operational revenue (+5,000 SGD) and multi-category expenses (-2,200 SGD). Validates P&L articulation, category adjudication, cash flow conservation, and 12,800.00 SGD ending cash.
3. **Case 3: Bank-Brokerage Transfer & Asset Swap (Zero P&L Contamination)**
   Executes a 5,000.00 SGD transfer from a commercial bank account to a brokerage portfolio account. Validates that net income remains strictly 0.00 SGD and total assets remain 20,000.00 SGD with zero P&L contamination.
4. **Case 4: Multi-National & Multi-Currency Consolidated Balance Sheet**
   Processes statements across 3 sovereign jurisdictions: Singapore (SGD), United States (USD), and Hong Kong (HKD). Mathematically asserts consolidated balance sheet balance in base currency (SGD) and target currency (USD) with $\Delta = 0.00$.
5. **Case 5: Multi-Asset Portfolio Integration & Securities Valuation**
   Imports brokerage position snapshots (AAPL, VT) into `AtomicPosition` and `ManagedPosition`. Sets authoritative market prices and asserts portfolio holdings presence, securities valuation integration on the balance sheet, and $\Delta = 0.00$.

---

## 📜 Benchmark Releases & Observatory History

- [v0.1.52 Detailed Benchmark Report](../benchmarks/v0.1.52/report.html) — Historical baseline run.

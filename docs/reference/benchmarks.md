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
| **Multi-PII Household Operations** | $Assets_{household} \equiv \sum Assets_{member}, Equity_{initial} \equiv \sum Equity_{member}$ | Deduplication is source-scoped; multiple family accounts consolidate without collision. |
| **Debt Clearance & Non-P&L Repayment** | $\Delta Liabilities \equiv -Repayment, \Delta P\&L = 0.00$ | Zero double-counting: credit card settlement clears liabilities without duplicating expenses. |
| **Retained Earnings Articulation** | $Closing\,Equity = Opening\,Equity + Net\,Income$ | Net income articulates directly into balance sheet retained earnings. |
| **Cash Flow Conservation** | $Beginning\,Cash + Net\,Cash\,Flow \equiv Ending\,Cash$ | Direct and indirect reconciliation equality. |
| **Multi-Currency Consolidation** | $Assets_{base} \equiv \sum (Assets_i \times FX_i)$ | Consolidated balance sheet balances with $\Delta = 0.00$ across base and foreign currencies. |
| **Holistic Multi-Asset Valuation** | $Net\,Worth \equiv Cash + Securities_{FMV} + Real\,Estate_{Appraisal}$ | Public equities and real estate appraisals integrate into consolidated net worth with $\Delta = 0.00$. |

---

## 🧪 V2 Benchmark Scenarios Suite

The V2 benchmark test matrix covers end-to-end multi-period accounting sufficiency:

1. **Case 1: Consecutive 4-Month Rollforward & Q1 Articulation**
   Chains 4 consecutive monthly statements (Jan 2025 Straits Capital PDF, Feb/Mar/Apr 2025 chained Standard Chartered PDFs). Validates $Month_{n+1} \equiv Month_n$, Q1 closing checkpoint ($Net\,Income = +5,849.25$ SGD, $Assets = 21,300.00$ SGD), and Month 4 transition into Q2 ($Net\,Income = +8,749.25$ SGD, $Assets = 24,200.00$ SGD).
2. **Case 2: Multi-PII Household Operations & Category Reconciliation**
   Simulates household multi-member operations: Husband's DBS Bank account (+5,000.00 revenue, -2,200.00 expenses) and Wife's Standard Chartered account (+3,500.00 salary, -400.00 living expenses). Validates source-scoped deduplication, multi-PII co-existence without collision, consolidated net operating income (+5,900.00 SGD), and 20,900.00 SGD ending cash.
3. **Case 3: Credit Card Liability & Non-P&L Repayment Clearance**
   Incurs 1,200.00 SGD in operating expenses on a credit card liability account, followed by a 1,200.00 SGD bank settlement payment outflow. Validates that the credit card liability is cleared to 0.00 SGD with zero double-counting of expenses (Net Income remains strictly -1,200.00 SGD).
4. **Case 4: Multi-National & Multi-Currency Consolidated Balance Sheet**
   Processes statements across 3 sovereign jurisdictions: Singapore (SGD), United States (USD), and Hong Kong (HKD). Mathematically asserts consolidated balance sheet balance in base currency (SGD) and target currency (USD) with $\Delta = 0.00$.
5. **Case 5: Holistic Multi-Asset & Tax Ecosystem**
   Combines liquid securities (AAPL, VT) via Interactive Brokers import, illiquid real estate property appraisal (350,000.00 USD) via DocuBench FHA 1004 appraisal fixture (`KpewWz3R.pdf`), and annual compensation/tax withholding verification via Form W-2 (`phovuuuk.pdf`) and Payslip (`Oe7iRM1G.pdf`). Asserts comprehensive wealth valuation integration on the balance sheet with $\Delta = 0.00$.

---

## 📜 Benchmark Releases & Observatory History

- [v0.1.52 Detailed Benchmark Report](../benchmarks/v0.1.52/report.html) — Historical baseline run.

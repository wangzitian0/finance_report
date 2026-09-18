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
| **Temporal Multi-Period Rollforward** | $Month_{n+1}\,Opening\,Cash \equiv Month_n\,Closing\,Cash$ | Exact continuity without temporal drift or leakage. |
| **Asset Reallocation / Internal Transfer** | $\Delta Revenue = 0.00, \Delta Expense = 0.00, \Delta Net\,Income = 0.00$ | Zero P&L contamination when swapping assets (e.g. Bank $\to$ Brokerage). |
| **Retained Earnings Articulation** | $Closing\,Equity = Opening\,Equity + Net\,Income$ | Net income articulates directly into balance sheet retained earnings. |
| **Cash Flow Conservation** | $Beginning\,Cash + Net\,Cash\,Flow \equiv Ending\,Cash$ | Direct and indirect reconciliation equality. |

---

## 📜 Recent Benchmark Releases

- [v0.1.52 Detailed Benchmark Report](../benchmarks/v0.1.52/report.html) — 2/2 Scenarios Balanced, 0.00 SGD Drift, 113.58s.

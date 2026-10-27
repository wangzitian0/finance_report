# 30 Core Wealth & Accounting Flows SSOT

> **Version**: `1.0.0`  
> **Source Registry**: [`common/meta/flows/thirty_flows_ssot.json`](../../common/meta/flows/thirty_flows_ssot.json)  
> **Compliance Test Suites**:
> - Backend: [`apps/backend/tests/flows/test_thirty_flows_consistency.py`](../../apps/backend/tests/flows/test_thirty_flows_consistency.py) (38/38 Invariant & Contract Tests)
> - Frontend: [`apps/frontend/src/__tests__/thirtyFlowsConsistency.test.tsx`](../../apps/frontend/src/__tests__/thirtyFlowsConsistency.test.tsx) (10/10 Component & Domain Invariant Tests)

---

## 1. Overview & Architectural Principles

Finance Report governs wealth and accounting integrity through **30 canonical business flows** organized into **7 domain pillars**. Each flow enforces strict invariant guarantees rooted in double-entry bookkeeping, immutability, and deterministic accounting reconciliation:

1. **Balance Chain Invariance**: Opening balance + inflows - outflows must exactly match closing balance without silent truncation.
2. **Double-Entry Equilibrium**: Total debits must equal total credits for every posted journal transaction (`sum(Debit) == sum(Credit)`).
3. **No Unposted State Drift**: Reporting surfaces and financial statements only present fully verified transactions, while out-of-balance conditions trigger explicit diagnostic triage.
4. **Audit Provenance & Cryptographic Traceability**: All financial statements drill down to immutable transaction line items and source documents anchored by SHA-256 digests.

---

## 2. Seven Canonical Domains Breakdown

### Domain 1: Ingestion & Multimodal Extraction (Flows 1–5)

Focuses on multi-source ingestion (PDF statements, CSV, receipts, and appraisal certificates) with OCR extraction and continuity validation.

| Flow ID | Flow Name (EN / 中文) | UI Surface | Frontend Component | Backend Endpoint | Invariant / Accounting Rule | Test Reference |
|---|---|---|---|---|---|---|
| **1** | Standard Statement Drag & Drop Upload and OCR<br>*(标准银行账单拖拽上传与解析)* | `/upload` | `StatementUploader` | `POST /statements/upload` | `Parsed opening + sum(IN) - sum(OUT) == calculated_closing` | [`apps/backend/tests/extraction/test_extraction_invariants.py`](../../apps/backend/tests/extraction/test_extraction_invariants.py) |
| **2** | Batch Multi-Month Ingestion & Continuity Gap Detection<br>*(多月份账单批量连续导入与断流预警)* | `/upload` | `StatementUploader` | `POST /statements/upload` | `Statement[M].closing_balance == Statement[M+1].opening_balance` | [`apps/backend/tests/accounting/test_account_statement_coverage.py`](../../apps/backend/tests/accounting/test_account_statement_coverage.py) |
| **3** | Custom Non-Standard CSV Column Mapping<br>*(非标机构 CSV 流水导入与表头映射)* | `/upload` | `StatementUploader` | `POST /statements/upload` | `All mapped rows have valid txn_date, description, and Decimal amount` | [`apps/backend/tests/extraction/test_csv_parsing.py`](../../apps/backend/tests/extraction/test_csv_parsing.py) |
| **4** | Physical Receipt & Screenshot Mobile Capture<br>*(纸质小票/手机银行截图拍照识别)* | `/portfolio?panel=evidence` | `GuidedEvidenceForm` | `POST /assets/valuation-snapshots` | `Evidence file anchored to transaction or asset with SHA-256 digest` | [`apps/backend/tests/api/test_assets_valuation_api.py`](../../apps/backend/tests/api/test_assets_valuation_api.py) |
| **5** | Alternative Asset Appraisal & Valuation Ingestion<br>*(不动产/车辆/私募等另类资产凭证录入)* | `/portfolio?panel=evidence` | `GuidedEvidenceForm` | `POST /assets/valuation-snapshots` | `Valuation creates journal entry adjusting Asset and UnrealizedGain` | [`apps/backend/tests/api/test_assets_valuation_api.py`](../../apps/backend/tests/api/test_assets_valuation_api.py) |

---

### Domain 2: Fact Review & Human-in-the-Loop (Flows 6–10)

Governs Stage-1 fact validation, mismatch defense, deduplication, rejection triage, and inline AI assistance.

| Flow ID | Flow Name (EN / 中文) | UI Surface | Frontend Component | Backend Endpoint | Invariant / Accounting Rule | Test Reference |
|---|---|---|---|---|---|---|
| **6** | Stage-1 Review Quick Human Approval<br>*(事实核对快速批准)* | `/statements/{id}` | `ReviewActionBar` | `POST /statements/{id}/review/approve` | `Approved statements create posted journal entries with matching custody account` | [`apps/backend/tests/api/test_statements_router.py`](../../apps/backend/tests/api/test_statements_router.py) |
| **7** | Stage-1 Balance Mismatch Defense & Rejection Guidance<br>*(链断裂防御与驳回重析引导)* | `/statements/{id}` | `LowConfidenceReviewModal` | `POST /statements/{id}/review/reject` | `Mismatch prevents silent corruption; rejects in-place mutation and routes to re-parse` | [`apps/backend/tests/api/test_statements_router.py`](../../apps/backend/tests/api/test_statements_router.py) |
| **8** | Cross-Statement Overlapping Transaction Deduplication<br>*(跨账单重叠交易去重)* | `/statements/{id}` | `ConflictResolutionDialog` | `POST /statements/{statement_id}/stage2/run-checks` | `Duplicate transactions flagged and linked without double-counting in ledger` | [`apps/backend/tests/extraction/test_deduplication.py`](../../apps/backend/tests/extraction/test_deduplication.py) |
| **9** | Low Quality Document Triage and Rejection Recovery<br>*(劣质文档排查与废弃)* | `/statements/{id}` | `ConfirmDialog` | `POST /statements/{id}/review/reject` | `Rejected statements excluded from general ledger and marked with taxonomy reason` | [`apps/backend/tests/api/test_statements_router.py`](../../apps/backend/tests/api/test_statements_router.py) |
| **10** | Contextual In-Page AI Assistant & Recovery<br>*(页内伴随式 AI 问答与容错)* | `/statements/{id}` | `StatementDetailPage` | `POST /chat` | `Metadata-preserving navigation: Chat prompt carries immutable statement metadata and gracefully recovers from SSE disconnects` | [`apps/backend/tests/api/test_statements_router.py`](../../apps/backend/tests/api/test_statements_router.py) |

---

### Domain 3: Economic Intent & Categorization (Flows 11–14)

Governs Stage-2 economic intent allocation, counter-account creation, batch clearing, and payroll gross-to-net deductions.

| Flow ID | Flow Name (EN / 中文) | UI Surface | Frontend Component | Backend Endpoint | Invariant / Accounting Rule | Test Reference |
|---|---|---|---|---|---|---|
| **11** | Stage-2 Interactive Economic Intent Allocation<br>*(未归类意图交互分配)* | `/reconciliation?tab=unmatched` | `UnmatchedBoard` | `POST /reconciliation/unmatched/{txn_id}/reviewed-disposition` | `Each transaction disposition assigns counter account and posts debit/credit` | [`apps/backend/tests/api/test_reconciliation_router.py`](../../apps/backend/tests/api/test_reconciliation_router.py) |
| **12** | Batch Rule Commit & Clearing<br>*(规则批量自动回填与提交)* | `/reconciliation?tab=review-queue` | `Stage2ReviewQueue` | `POST /statements/batch-approve-matches` | `Batch approve commits all matching rules atomically when checks resolved` | [`apps/backend/tests/api/test_statements_router.py`](../../apps/backend/tests/api/test_statements_router.py) |
| **13** | On-the-Fly Counter Account Creation During Review<br>*(审核中即时新建会计科目)* | `/reconciliation?tab=unmatched` | `UnmatchedBoard` | `POST /accounts` | `Created account is added to choices but requires explicit reviewer confirmation (AC-reconciliation.first-use.1)` | [`apps/backend/tests/accounting/test_accounts_endpoints.py`](../../apps/backend/tests/accounting/test_accounts_endpoints.py) |
| **14** | Payroll Gross-to-Net & Tax/CPF Deductions Split<br>*(薪资净额与税费/公积金拆分)* | `/journal` | `JournalPage` | `POST /journal-entries` | `Gross Salary == Net Cash Payout + Income Tax Withholding + Employee Pension Deductions` | [`apps/backend/tests/reporting/test_bench_articulation_matrix.py`](../../apps/backend/tests/reporting/test_bench_articulation_matrix.py) |

---

### Domain 4: Cross-Source Reconciliation & Transfers (Flows 15–18)

Governs internal transfer pairing, credit card repayment clearing, multi-currency realized FX decomposition, and penny rounding write-off.

| Flow ID | Flow Name (EN / 中文) | UI Surface | Frontend Component | Backend Endpoint | Invariant / Accounting Rule | Test Reference |
|---|---|---|---|---|---|---|
| **15** | Inter-Account Transfer Automatic Pairing<br>*(内部转账自动配对)* | `/reconciliation` | `Workbench` | `POST /reconciliation/runs` | `Source account Dr == Target account Cr; Transfer clearing account net balance == 0` | [`apps/backend/tests/reconciliation/test_reconciliation_matching_unit.py`](../../apps/backend/tests/reconciliation/test_reconciliation_matching_unit.py) |
| **16** | Credit Card Repayment & Refund Clearing<br>*(信用卡还款勾稽)* | `/reconciliation` | `Workbench` | `POST /reconciliation/matches/{match_id}/accept` | `Bank cash outflow Dr CreditCardLiability == Credit card statement payment Inflow` | [`tests/tooling/test_benchmark_scenario_suite.py`](../../tests/tooling/test_benchmark_scenario_suite.py) |
| **17** | Multi-Currency Transfer Realized FX Gain/Loss Decomposition<br>*(跨币种电汇汇兑损益分解)* | `/journal` | `JournalPage` | `POST /journal-entries` | `OutflowValueInBase + RealizedGain == InflowValueInBase + RealizedLoss` | [`apps/backend/tests/reporting/test_bench_articulation_matrix.py`](../../apps/backend/tests/reporting/test_bench_articulation_matrix.py) |
| **18** | Reconciliation Immaterial Adjustment & Penny Rounding Write-Off<br>*(悬空微小差额平账)* | `/reconciliation` | `ReconciliationPage` | `POST /reconciliation/adjustment` | `Immaterial discrepancy (|delta| <= 0.05) balances to BankRoundingDifference` | [`apps/backend/tests/api/test_reconciliation_adjustment_api.py`](../../apps/backend/tests/api/test_reconciliation_adjustment_api.py) |

---

### Domain 5: Investments & Multi-Asset Valuation (Flows 19–22)

Governs brokerage statement positions, dividend tax withholding, market price updates, and mortgage principal amortization.

| Flow ID | Flow Name (EN / 中文) | UI Surface | Frontend Component | Backend Endpoint | Invariant / Accounting Rule | Test Reference |
|---|---|---|---|---|---|---|
| **19** | Brokerage Monthly Statement Position Sync<br>*(券商月结单持仓更新)* | `/portfolio` | `HoldingsTable` | `POST /statements/upload` | `Position quantity * average_cost == Book cost; synced across statement boundaries` | [`apps/backend/tests/extraction/test_brokerage_position_extraction_wiring.py`](../../apps/backend/tests/extraction/test_brokerage_position_extraction_wiring.py) |
| **20** | Dividend Gross-to-Net & Withholding Tax Split<br>*(股票分红预扣税拆分)* | `/reconciliation?tab=unmatched` | `UnmatchedBoard` | `POST /journal-entries` | `Gross Dividend Income == Net Cash Received + Withholding Tax Expense` | [`apps/backend/tests/reporting/test_bench_articulation_matrix.py`](../../apps/backend/tests/reporting/test_bench_articulation_matrix.py) |
| **21** | Real-Time Market Price Refresh & Unrealized PnL<br>*(实时市价刷新与重估)* | `/portfolio?panel=prices` | `PriceUpdateForm` | `POST /portfolio/prices/update` | `Market value == Quantity * Latest Price; Unrealized PnL == Market value - Cost` | [`apps/backend/tests/pricing/test_valuation_lines.py`](../../apps/backend/tests/pricing/test_valuation_lines.py) |
| **22** | Mortgage Principal Amortization and Interest Split<br>*(房贷月供本息摊销拆解)* | `/reconciliation?tab=unmatched` | `UnmatchedBoard` | `POST /journal-entries` | `Total Mortgage Payment == Principal Reduction (Liability) + Interest Expense` | [`apps/backend/tests/reporting/test_bench_articulation_matrix.py`](../../apps/backend/tests/reporting/test_bench_articulation_matrix.py) |

---

### Domain 6: Financial Reporting & Accounting Equation Governance (Flows 23–26)

Governs balance sheet equation validation, out-of-balance root cause diagnostic triage, comparative income trends, and cash flow tripartite reconciliation.

| Flow ID | Flow Name (EN / 中文) | UI Surface | Frontend Component | Backend Endpoint | Invariant / Accounting Rule | Test Reference |
|---|---|---|---|---|---|---|
| **23** | Balance Sheet Accounting Equation Validation<br>*(资产负债表恒等式检验)* | `/reports?tab=balance-sheet` | `BalanceSheetPanel` | `GET /reports/balance-sheet` | `Assets == Liabilities + Equity + RetainedEarnings (Equation Delta == 0.00)` | [`apps/backend/tests/ledger/test_accounting_equation.py`](../../apps/backend/tests/ledger/test_accounting_equation.py) |
| **24** | Accounting Equation Out-of-Balance Diagnostic Triage<br>*(会计恒等式失衡智能排错)* | `/reports?tab=balance-sheet` | `BalanceSheetPanel` | `GET /reports/balance-sheet/diagnostics` | `When Equation Delta != 0, returns classified cause: UNPOSTED_DRAFT, FX_ROUNDING_DRIFT, UNKNOWN_DISCREPANCY` | [`apps/backend/tests/reporting/test_equation_diagnostics.py`](../../apps/backend/tests/reporting/test_equation_diagnostics.py) |
| **25** | Income Statement Comparative Trend Analysis<br>*(损益表多期环比分析)* | `/reports?tab=income-statement` | `IncomeStatementPanel` | `GET /reports/income-statement` | `Comparative periodic columns display balance variations without silent drop` | [`apps/backend/tests/reporting/test_reports_router.py`](../../apps/backend/tests/reporting/test_reports_router.py) |
| **26** | Cash Flow Statement Multi-Activity Invariant Verification<br>*(现金流量表健康度与自洽检验)* | `/reports?tab=cash-flow` | `CashFlowPanel` | `GET /reports/cash-flow` | `Net Cash Change == Operating Cash Flow + Investing Cash Flow + Financing Cash Flow` | [`apps/backend/tests/reporting/test_cash_flow_invariants.py`](../../apps/backend/tests/reporting/test_cash_flow_invariants.py) |

---

### Domain 7: Audit Traceability, Compliance & AI Insights (Flows 27–30)

Governs PDF provenance drilldown, annual tax zip export with SHA-256 manifests, recurring subscription anomaly detection, and read-only AI advisory.

| Flow ID | Flow Name (EN / 中文) | UI Surface | Frontend Component | Backend Endpoint | Invariant / Accounting Rule | Test Reference |
|---|---|---|---|---|---|---|
| **27** | Financial Report to PDF Provenance Drilldown<br>*(报表到 PDF 凭证穿透)* | `/reports?tab=balance-sheet` | `ProvenanceBadge` | `GET /reports/account-lineage` | `Report Line drilldown traces to underlying journal entries and source statement metadata` | [`apps/backend/tests/reporting/test_reports_router.py`](../../apps/backend/tests/reporting/test_reports_router.py) |
| **28** | Annual Tax & Audit Package ZIP Export<br>*(年度报税合规包导出)* | `/reports?tab=package` | `PackagePanel` | `POST /reports/package/annual-archive` | `ZIP contains manifest.json with SHA-256 hashes of all schedule CSVs and audit trail` | [`apps/backend/tests/reporting/test_annual_tax_package.py`](../../apps/backend/tests/reporting/test_annual_tax_package.py) |
| **29** | Recurring Subscriptions & Anomaly Alerts<br>*(周期扣费/重复扣款异常告警)* | `/upload` | `WorkflowNotices` | `GET /reconciliation/transactions/{txn_id}/anomalies` | `Identifies recurring cadence and flags unexpected amount increases or duplicate runs` | [`apps/backend/tests/reconciliation/test_anomaly_detection.py`](../../apps/backend/tests/reconciliation/test_anomaly_detection.py) |
| **30** | Natural Language Financial AI Assistant with Tool Calling<br>*(自然语言财务 AI 顾问)* | `/chat` | `ChatPageClient` | `POST /chat` | `AI operates in read-only sandbox calling accounting queries with streaming response` | [`apps/backend/tests/ai/test_ai_advisor_service.py`](../../apps/backend/tests/ai/test_ai_advisor_service.py) |

---

## 3. Invariant Verification & Execution

To continuously guard against regression, both backend and frontend suites validate that every flow contract aligns with the codebase:

```bash
# 1. Backend 30-Flow consistency suite (38 tests)
apps/backend/.venv/bin/pytest apps/backend/tests/flows/test_thirty_flows_consistency.py -o addopts=""

# 2. Frontend 30-Flow consistency suite (10 tests)
cd apps/frontend && npx vitest run src/__tests__/thirtyFlowsConsistency.test.tsx

# 3. Router contract-maturity gate
python tools/audit_router_contracts.py --output docs/reference/router-contract-maturity.md
```

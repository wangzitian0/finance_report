# 30 Core Wealth & Accounting Flows SSOT

> **Version**: `1.0.0`  
> **Source Registry**: [`common/meta/flows/thirty_flows_ssot.json`](../../common/meta/flows/thirty_flows_ssot.json)  
> **Compliance Test Suites**:
> - Backend: [`apps/backend/tests/flows/test_thirty_flows_consistency.py`](../../apps/backend/tests/flows/test_thirty_flows_consistency.py) (36/36 Invariant & Contract Tests)
> - Frontend: [`apps/frontend/src/__tests__/thirtyFlowsConsistency.test.tsx`](../../apps/frontend/src/__tests__/thirtyFlowsConsistency.test.tsx) (11/11 Next.js Route & Component Tests)

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
| **3** | Custom Non-Standard CSV Column Mapping<br>*(非标机构 CSV 流水导入与表头映射)* | `/upload` | `StatementUploader` | `POST /statements/upload` | All mapped rows must contain valid `txn_date`, non-empty `description`, and `Decimal` amount. | [`apps/backend/tests/extraction/test_csv_parsing.py`](../../apps/backend/tests/extraction/test_csv_parsing.py) |
| **4** | Physical Receipt & Screenshot Mobile Capture<br>*(纸质小票/手机银行截图拍照识别)* | `/portfolio/evidence` | `GuidedEvidenceForm` | `POST /assets/valuation-snapshots` | Evidence artifact anchored to transaction or asset position with SHA-256 digest. | [`apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx`](../../apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx) |
| **5** | Alternative Asset Appraisal & Valuation Ingestion<br>*(不动产/车辆/私募等另类资产凭证录入)* | `/assets` | `AssetsPage` | `POST /assets/valuation-snapshots` | Appraisal valuation records adjustments balancing Asset value against Unrealized Gain/Loss. | [`apps/backend/tests/assets/test_assets_router.py`](../../apps/backend/tests/assets/test_assets_router.py) |

---

### Domain 2: Fact Review & Human-in-the-Loop (Flows 6–10)

Governs Stage-1 fact validation, mismatch defense, deduplication, rejection triage, and inline AI assistance.

| Flow ID | Flow Name (EN / 中文) | UI Surface | Frontend Component | Backend Endpoint | Invariant / Accounting Rule | Test Reference |
|---|---|---|---|---|---|---|
| **6** | Stage-1 Review Quick Human Approval<br>*(事实核对快速批准)* | `/statements/{id}/review` | `ReviewActionBar` | `POST /statements/{id}/review/approve` | Approved statement creates posted journal entries matching custody account. | [`apps/frontend/src/__tests__/statementReviewPage.test.tsx`](../../apps/frontend/src/__tests__/statementReviewPage.test.tsx) |
| **7** | Stage-1 Balance Mismatch Defense & Rejection Guidance<br>*(链断裂防御与驳回重析引导)* | `/statements/{id}/review` | `LowConfidenceReviewModal` | `POST /statements/{id}/review/reject` | Balance chain mismatch halts posting, rejects in-place mutation, and routes document to re-parse. | [`apps/frontend/src/__tests__/statementReviewPage.test.tsx`](../../apps/frontend/src/__tests__/statementReviewPage.test.tsx) |
| **8** | Cross-Statement Overlapping Transaction Deduplication<br>*(跨账单重叠交易去重)* | `/statements/{id}/review` | `ConflictResolutionDialog` | `POST /review/conflicts/{id}/resolve` | Duplicate transactions flagged and linked without double-counting in ledger balances. | [`apps/backend/tests/extraction/test_deduplication.py`](../../apps/backend/tests/extraction/test_deduplication.py) |
| **9** | Low Quality Document Triage and Rejection Recovery<br>*(劣质文档排查与废弃)* | `/statements/{id}` | `ConfirmDialog` | `POST /statements/{id}/review/reject` | Rejected statements excluded from general ledger and marked with taxonomy reason. | [`apps/backend/tests/api/test_statements_router.py`](../../apps/backend/tests/api/test_statements_router.py) |
| **10** | Contextual In-Page AI Assistant & Recovery<br>*(页内伴随式 AI 问答与容错)* | `/statements/{id}/review` | `StatementAiAssistantButton` | `POST /chat` | Chat prompt carries immutable statement metadata and gracefully recovers from SSE disconnects. | [`apps/frontend/src/__tests__/StatementAiAssistantButton.test.tsx`](../../apps/frontend/src/__tests__/StatementAiAssistantButton.test.tsx) |

---

### Domain 3: Economic Intent & Categorization (Flows 11–14)

Governs Stage-2 economic intent allocation, counter-account creation, batch clearing, and payroll gross-to-net deductions.

| Flow ID | Flow Name (EN / 中文) | UI Surface | Frontend Component | Backend Endpoint | Invariant / Accounting Rule | Test Reference |
|---|---|---|---|---|---|---|
| **11** | Stage-2 Interactive Economic Intent Allocation<br>*(未归类意图交互分配)* | `/reconciliation/unmatched` | `UnmatchedBoard` | `POST /reconciliation/unmatched/{txn_id}/reviewed-disposition` | Each transaction disposition assigns counter account and posts balanced debit/credit entries. | [`apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx`](../../apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx) |
| **12** | Batch Rule Commit & Clearing<br>*(规则批量自动回填与提交)* | `/reconciliation/review-queue` | `Stage2ReviewQueue` | `POST /statements/batch-approve-matches` | Batch approve commits all matching rules atomically when validation checks resolve. | [`apps/frontend/src/__tests__/reviewQueuePage.test.tsx`](../../apps/frontend/src/__tests__/reviewQueuePage.test.tsx) |
| **13** | On-the-Fly Counter Account Creation During Review<br>*(审核中即时新建会计科目)* | `/reconciliation/unmatched` | `UnmatchedBoard` | `POST /accounts` | Created account is added to choices and requires explicit reviewer confirmation (`AC-reconciliation.first-use.1`). | [`apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx`](../../apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx) |
| **14** | Payroll Gross-to-Net & Tax/CPF Deductions Split<br>*(薪资净额与税费/公积金拆分)* | `/journal` | `JournalPage` | `POST /journal-entries` | `Gross Salary == Net Cash Payout + Income Tax Withholding + Employee Deductions` | [`apps/backend/tests/reconciliation/test_specialized_splits.py`](../../apps/backend/tests/reconciliation/test_specialized_splits.py) |

---

### Domain 4: Cross-Source Reconciliation & Transfers (Flows 15–18)

Governs internal transfer pairing, credit card repayment clearing, multi-currency realized FX decomposition, and penny rounding write-off.

| Flow ID | Flow Name (EN / 中文) | UI Surface | Frontend Component | Backend Endpoint | Invariant / Accounting Rule | Test Reference |
|---|---|---|---|---|---|---|
| **15** | Inter-Account Transfer Automatic Pairing<br>*(内部转账自动配对)* | `/reconciliation` | `Workbench` | `POST /reconciliation/runs` | Source account Dr == Target account Cr; Transfer clearing account net balance == 0. | [`apps/backend/tests/reconciliation/test_reconciliation_matching_unit.py`](../../apps/backend/tests/reconciliation/test_reconciliation_matching_unit.py) |
| **16** | Credit Card Repayment & Refund Clearing<br>*(信用卡还款勾稽)* | `/reconciliation` | `Workbench` | `POST /reconciliation/matches/{match_id}/accept` | `Bank Outflow (Dr CreditCardLiability) == Credit Card Payment Inflow`. | [`apps/backend/tests/e2e/test_core_journeys.py`](../../apps/backend/tests/e2e/test_core_journeys.py) |
| **17** | Multi-Currency Transfer Realized FX Gain/Loss Decomposition<br>*(跨币种电汇汇兑损益分解)* | `/journal` | `JournalPage` | `POST /journal-entries` | `OutflowValueInBase + RealizedGain == InflowValueInBase + RealizedLoss`. | [`apps/backend/tests/reconciliation/test_specialized_splits.py`](../../apps/backend/tests/reconciliation/test_specialized_splits.py) |
| **18** | Reconciliation Immaterial Adjustment & Penny Rounding Write-Off<br>*(悬空微小差额平账)* | `/reconciliation` | `ReconciliationPage` | `POST /reconciliation/adjustment` | Immaterial discrepancy (`|Delta| <= 0.05`) balances against BankRoundingDifference. | [`apps/backend/tests/api/test_reconciliation_adjustment_api.py`](../../apps/backend/tests/api/test_reconciliation_adjustment_api.py) |

---

### Domain 5: Investments & Multi-Asset Valuation (Flows 19–22)

Governs brokerage statement positions, dividend tax withholding, market price updates, and mortgage principal amortization.

| Flow ID | Flow Name (EN / 中文) | UI Surface | Frontend Component | Backend Endpoint | Invariant / Accounting Rule | Test Reference |
|---|---|---|---|---|---|---|
| **19** | Brokerage Monthly Statement Position Sync<br>*(券商月结单持仓更新)* | `/portfolio` | `HoldingsTable` | `POST /statements/upload` | `Position Quantity * Average Cost == Book Cost`; continuous across statement boundaries. | [`apps/backend/tests/extraction/test_brokerage_position_extraction_wiring.py`](../../apps/backend/tests/extraction/test_brokerage_position_extraction_wiring.py) |
| **20** | Dividend Gross-to-Net & Withholding Tax Split<br>*(股票分红预扣税拆分)* | `/reconciliation/unmatched` | `UnmatchedBoard` | `POST /journal-entries` | `Gross Dividend Income == Net Cash Received + Withholding Tax Expense`. | [`apps/backend/tests/reconciliation/test_specialized_splits.py`](../../apps/backend/tests/reconciliation/test_specialized_splits.py) |
| **21** | Real-Time Market Price Refresh & Unrealized PnL<br>*(实时市价刷新与重估)* | `/portfolio/prices` | `PricesPage` | `POST /portfolio/prices/update` | `Market Value == Quantity * Latest Price; Unrealized PnL == Market Value - Cost`. | [`apps/frontend/src/__tests__/portfolioPricesPage.test.tsx`](../../apps/frontend/src/__tests__/portfolioPricesPage.test.tsx) |
| **22** | Mortgage Principal Amortization and Interest Split<br>*(房贷月供本息摊销拆解)* | `/reconciliation/unmatched` | `UnmatchedBoard` | `POST /journal-entries` | `Total Mortgage Payment == Principal Reduction + Interest Expense`. | [`apps/backend/tests/reconciliation/test_specialized_splits.py`](../../apps/backend/tests/reconciliation/test_specialized_splits.py) |

---

### Domain 6: Financial Reporting & Accounting Equation Governance (Flows 23–26)

Governs balance sheet equation validation, out-of-balance root cause diagnostic triage, comparative income trends, and cash flow tripartite reconciliation.

| Flow ID | Flow Name (EN / 中文) | UI Surface | Frontend Component | Backend Endpoint | Invariant / Accounting Rule | Test Reference |
|---|---|---|---|---|---|---|
| **23** | Balance Sheet Accounting Equation Validation<br>*(资产负债表恒等式检验)* | `/reports/balance-sheet` | `BalanceSheetPage` | `GET /reports/balance-sheet` | `Assets == Liabilities + Equity + RetainedEarnings` (`Delta == 0.00`). | [`apps/backend/tests/ledger/test_accounting_equation.py`](../../apps/backend/tests/ledger/test_accounting_equation.py) |
| **24** | Accounting Equation Out-of-Balance Diagnostic Triage<br>*(会计恒等式失衡智能排错)* | `/reports/balance-sheet` | `BalanceSheetPage` | `GET /reports/balance-sheet/diagnostics` | When `Delta != 0`, returns classified root causes (`UNPOSTED_DRAFT`, `ONE_SIDED`, `UNMAPPED`, `FX_DRIFT`). | [`apps/backend/tests/reporting/test_equation_diagnostics.py`](../../apps/backend/tests/reporting/test_equation_diagnostics.py) |
| **25** | Income Statement Comparative Trend Analysis<br>*(损益表多期环比分析)* | `/reports/income-statement` | `IncomeStatementPage` | `GET /reports/income-statement` | Comparative periodic columns display balance variations without silent item omission. | [`apps/frontend/src/__tests__/incomeStatementPage.test.tsx`](../../apps/frontend/src/__tests__/incomeStatementPage.test.tsx) |
| **26** | Cash Flow Statement Multi-Activity Invariant Verification<br>*(现金流量表健康度与自洽检验)* | `/reports/cash-flow` | `CashFlowPage` | `GET /reports/cash-flow` | `Net Cash Change == Operating CF + Investing CF + Financing CF`. | [`apps/backend/tests/reporting/test_reports_router.py`](../../apps/backend/tests/reporting/test_reports_router.py) |

---

### Domain 7: Audit Traceability, Compliance & AI Insights (Flows 27–30)

Governs PDF provenance drilldown, annual tax zip export with SHA-256 manifests, recurring subscription anomaly detection, and read-only AI advisory.

| Flow ID | Flow Name (EN / 中文) | UI Surface | Frontend Component | Backend Endpoint | Invariant / Accounting Rule | Test Reference |
|---|---|---|---|---|---|---|
| **27** | Financial Report to PDF Provenance Drilldown<br>*(报表到 PDF 凭证穿透)* | `/reports/balance-sheet` | `ProvenanceBadge` | `GET /reports/account-lineage` | Report line drilldown traces to underlying journal entries and source statement metadata. | [`apps/frontend/src/__tests__/provenanceBadge.test.tsx`](../../apps/frontend/src/__tests__/provenanceBadge.test.tsx) |
| **28** | Annual Tax & Audit Package ZIP Export<br>*(年度报税合规包导出)* | `/reports/package` | `PersonalReportPackagePage` | `POST /reports/package/annual-archive` | ZIP export contains `manifest.json` with SHA-256 digests of all schedule CSVs and audit trail. | [`apps/backend/tests/reporting/test_annual_tax_package.py`](../../apps/backend/tests/reporting/test_annual_tax_package.py) |
| **29** | Recurring Subscriptions & Anomaly Alerts<br>*(周期扣费/重复扣款异常告警)* | `/notifications` | `WorkflowEventsPageContent` | `GET /notifications` | Identifies recurring cadence and flags unexpected amount surges or duplicate transaction executions. | [`apps/backend/tests/reconciliation/test_anomaly_detection.py`](../../apps/backend/tests/reconciliation/test_anomaly_detection.py) |
| **30** | Natural Language Financial AI Assistant with Tool Calling<br>*(自然语言财务 AI 顾问)* | `/chat` | `ChatPageClient` | `POST /chat` | AI executes queries within a read-only sandbox with streaming SSE responses. | [`apps/frontend/src/__tests__/chatPage.test.tsx`](../../apps/frontend/src/__tests__/chatPage.test.tsx) |

---

## 3. Invariant Verification & Execution

To continuously guard against regression, both backend and frontend suites validate that every flow contract aligns with the codebase:

```bash
# 1. Backend 30-Flow consistency suite (36 tests)
apps/backend/.venv/bin/pytest apps/backend/tests/flows/test_thirty_flows_consistency.py -o addopts=""

# 2. Frontend 30-Flow consistency suite (11 tests)
cd apps/frontend && npx vitest run src/__tests__/thirtyFlowsConsistency.test.tsx

# 3. Router contract-maturity gate
python tools/audit_router_contracts.py --output docs/reference/router-contract-maturity.md
```

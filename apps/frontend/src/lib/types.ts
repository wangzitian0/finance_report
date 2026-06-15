/**
 * Shared Type Definitions
 */

import type { Schemas } from "./api-schema";

export type DecimalValue = string;
export type MoneyValue = DecimalValue;
export type DataProvenance = "imported" | "manual" | "derived";
export const MONEY_VALUE_CONTRACT = "decimal-string" as const;

export interface Account {
  id: string;
  name: string;
  code?: string;
  type: "ASSET" | "LIABILITY" | "EQUITY" | "INCOME" | "EXPENSE";
  currency: string;
  description?: string;
  parent_id?: string | null;
  is_active: boolean;
  balance?: MoneyValue;
}

export interface AccountListResponse {
  items: Account[];
  total: number;
}

export interface JournalLine {
  id: string;
  account_id: string;
  direction: "DEBIT" | "CREDIT";
  amount: MoneyValue;
  currency: string;
  fx_rate?: DecimalValue | null;
}

export interface JournalEntry {
  id: string;
  entry_date: string;
  memo: string;
  source_type: string;
  confidence_tier?: "TRUSTED" | "HIGH" | "MEDIUM" | "LOW" | null;
  status: "draft" | "posted" | "reconciled" | "void";
  lines: JournalLine[];
  created_at: string;
  // Summary view properties
  total_amount?: MoneyValue;
}

export type JournalEntrySummary = Schemas["JournalEntrySummary"];

export interface JournalEntryListResponse {
  items: JournalEntry[];
  total: number;
}

export interface BankStatementTransaction {
  id: string;
  statement_id: string;
  txn_date: string;
  description: string;
  amount: MoneyValue;
  direction: string;
  reference?: string | null;
  currency?: string | null;
  balance_after?: MoneyValue | null;
  status: "pending" | "matched" | "unmatched";
  confidence: "high" | "medium" | "low";
  confidence_tier?: "TRUSTED" | "HIGH" | "MEDIUM" | "LOW";
  confidence_reason?: string | null;
  raw_text?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BankStatementTransactionSummary {
  id: string;
  statement_id: string;
  txn_date: string;
  description: string;
  amount: MoneyValue;
  direction: string;
  currency?: string | null;
  reference?: string | null;
  status: "pending" | "matched" | "unmatched";
  confidence_tier?: "TRUSTED" | "HIGH" | "MEDIUM" | "LOW";
}

export interface BankStatement {
  id: string;
  user_id: string;
  account_id?: string | null;
  file_path: string;
  original_filename: string;
  institution: string;
  account_last4?: string | null;
  currency?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  opening_balance?: MoneyValue | null;
  closing_balance?: MoneyValue | null;
  status: "uploaded" | "parsing" | "parsed" | "approved" | "rejected";
  confidence_score?: number | null;
  balance_validated?: boolean | null;
  validation_error?: string | null;
  created_at: string;
  updated_at: string;
  transactions: BankStatementTransaction[];
}

export interface BankStatementListResponse {
  items: BankStatement[];
  total: number;
}

export type ReportLine = Schemas["ReportLine"];

export type AccountLineageLine = Schemas["AccountLineageLine"];

export type AccountLineageResponse = Schemas["AccountLineageResponse"];

export interface FxWarning {
  type: string;
  message?: string;
  from_currency?: string;
  to_currency?: string;
  date?: string;
  fallback_date?: string;
  source?: string;
  [key: string]: string | undefined;
}

export interface BalanceSheetResponse {
  as_of_date: string;
  currency: string;
  assets: ReportLine[];
  liabilities: ReportLine[];
  equity: ReportLine[];
  total_assets: MoneyValue;
  total_liabilities: MoneyValue;
  total_equity: MoneyValue;
  net_income?: MoneyValue;
  unrealized_fx_gain_loss?: MoneyValue;
  net_worth_adjustment_gain_loss?: MoneyValue;
  fx_warnings?: FxWarning[];
  equation_delta: MoneyValue;
  is_balanced: boolean;
}

export type IncomeStatementTrend = Schemas["IncomeStatementTrend"];

export interface IncomeStatementResponse {
  start_date: string;
  end_date: string;
  currency: string;
  income: ReportLine[];
  expenses: ReportLine[];
  total_income: MoneyValue;
  total_expenses: MoneyValue;
  net_income: MoneyValue;
  fx_warnings?: FxWarning[];
  trends: IncomeStatementTrend[];
  filters_applied?: {
    tags: string[] | null;
    account_type: string | null;
  };
}

export type CashFlowItem = Schemas["CashFlowItem"];

export type CashFlowSummary = Schemas["CashFlowSummary"];

export interface CashFlowResponse {
  start_date: string;
  end_date: string;
  currency: string;
  operating: CashFlowItem[];
  investing: CashFlowItem[];
  financing: CashFlowItem[];
  summary: CashFlowSummary;
  fx_warnings?: FxWarning[];
}

export type PersonalReportPackageSectionContract = Schemas["PersonalReportPackageSectionContract"];

export interface PersonalReportPackageContractResponse {
  package_id: string;
  version: string;
  period_semantics: Record<string, string>;
  supported_frameworks: string[];
  selected_framework_id?: string | null;
  framework_policy_endpoint?: string | null;
  sections: PersonalReportPackageSectionContract[];
  export_contract: {
    formats: string[];
    csv_columns: string[];
  };
}

export type PersonalReportPackageReadinessBlocker = Schemas["PersonalReportPackageReadinessBlocker"];

export interface PersonalReportPackageReadinessResponse {
  package_id: string;
  state: "ready" | "processing" | "blocked" | "draft" | "generated" | "stale";
  label: string;
  action_href: string;
  blocking_count: number;
  blockers: PersonalReportPackageReadinessBlocker[];
  source_summary: Record<string, number | string>;
  source_trust_summary?: {
    source_classes: string[];
    deterministic_pr_source_classes: string[];
    post_merge_llm_ocr_source_classes: string[];
    manual_trusted_source_classes: string[];
    gap_source_classes: string[];
    blocker_codes: string[];
  };
  generated_at?: string | null;
  stale_since?: string | null;
}

export interface PersonalReportPackageSnapshotPayload {
  package_id: string;
  version: string;
  status: "draft" | "trusted";
  generated_at: string;
  framework_id: string;
  start_date: string;
  end_date: string;
  as_of_date: string;
  currency: string;
  readiness: PersonalReportPackageReadinessResponse;
  source_trust_summary?: PersonalReportPackageReadinessResponse["source_trust_summary"];
  section_payloads: Record<string, unknown>;
}

export type PersonalReportPackageSnapshotSummary = Schemas["PersonalReportPackageSnapshotSummary"];

export type PersonalReportPackageSnapshotResponse = Schemas["PersonalReportPackageSnapshotResponse"];

export interface AdvisorSuggestion {
  basis: string;
  confidence_tier: string;
  source_refs: string[];
  limitation: string;
  next_action_href: string;
}

export interface ChatCitation {
  label: string;
  source_ref: string;
  confidence_tier: string;
  href: string;
}

export interface ChatActionChip {
  kind: string;
  label: string;
  href: string;
  count?: number | null;
}

export interface ChatResponseMetadata {
  grounded: boolean;
  citations: ChatCitation[];
  actions: ChatActionChip[];
}

export interface ChatSuggestionsResponse {
  suggestions: string[];
  structured_suggestions?: AdvisorSuggestion[];
}

export type PersonalReportPackageNote = Schemas["PersonalReportPackageNote"];

export type PersonalReportPackageNotesResponse = Schemas["PersonalReportPackageNotesResponse"];

export type PersonalReportPackageTraceabilityAnchor = Schemas["PersonalReportPackageTraceabilityAnchor"];

export type PersonalReportPackageTraceabilityLine = Schemas["PersonalReportPackageTraceabilityLine"];

export type PersonalReportPackageCompletenessWarning = Schemas["PersonalReportPackageCompletenessWarning"];

export type PersonalReportPackageTraceabilityResponse = Schemas["PersonalReportPackageTraceabilityResponse"];

export type EvidenceLineageNode = Schemas["EvidenceLineageNode"];

export type EvidenceLineageEdge = Schemas["EvidenceLineageEdge"];

export type EvidenceLineageBlocker = Schemas["EvidenceLineageBlocker"];

export type EvidenceLineageResponse = Schemas["EvidenceLineageResponse"];

export interface FrameworkPolicyEvidenceAnchor {
  anchor_id: string;
  anchor_type: string;
  source_system: string;
  source_id: string;
  description?: string | null;
}

export interface FrameworkPolicyDecision {
  domain: string;
  recognition?: string | null;
  measurement?: string | null;
  classification?: string | null;
  presentation?: string | null;
  disclosure?: string | null;
  line_mappings: Record<string, string>;
  evidence_anchors: FrameworkPolicyEvidenceAnchor[];
  provenance: string;
  confidence_tier: string;
  review_state: string;
  policy_field_name: string;
  accepted_value?: string | null;
}

export interface FrameworkPolicyGap {
  code: string;
  fact_id: string;
  domain: string;
  instrument_type: string;
  blocker: boolean;
  reason: string;
  remediation: string;
  evidence_anchors: FrameworkPolicyEvidenceAnchor[];
}

export interface FrameworkPolicyResult {
  result_id: string;
  framework_id: string;
  matrix_version: string;
  report_period_start: string;
  report_period_end: string;
  generated_at: string;
  required_statements: string[];
  decisions: FrameworkPolicyDecision[];
  gaps: FrameworkPolicyGap[];
}

export type WorkflowPrimaryState =
  | "empty"
  | "processing"
  | "needs_action"
  | "blocked"
  | "ready";

export type WorkflowNextActionType =
  | "upload"
  | "wait"
  | "review_required"
  | "resolve_blocker"
  | "open_report"
  | "none";

export type WorkflowReportReadinessState =
  | "none"
  | "processing"
  | "ready"
  | "blocked"
  | "stale";

export type WorkflowEventFamily =
  | "source.uploaded"
  | "source.parsing.started"
  | "source.parsing.completed"
  | "source.parsing.failed"
  | "record.validation.passed"
  | "record.validation.failed"
  | "ledger.auto_posted"
  | "review.required"
  | "review.completed"
  | "reconciliation.blocked"
  | "report.processing"
  | "report.ready"
  | "report.blocked"
  | "report.generated";

export type WorkflowEventSeverity =
  | "info"
  | "success"
  | "warning"
  | "action_required"
  | "blocked";

export type WorkflowEventStatus = "unread" | "read" | "archived";

export type WorkflowReportImpact =
  | "none"
  | "processing"
  | "ready"
  | "blocked"
  | "stale";

export type WorkflowSessionStatus = "active" | "generated" | "archived";

export type WorkflowNextActionResponse = Schemas["WorkflowNextActionResponse"];

export type WorkflowReportReadinessResponse = Schemas["WorkflowReportReadinessResponse"];

export type WorkflowEventCountsResponse = Schemas["WorkflowEventCountsResponse"];

export type WorkflowSessionSummaryResponse = Schemas["WorkflowSessionSummaryResponse"];

export type WorkflowStatusResponse = Schemas["WorkflowStatusResponse"];

export type WorkflowEventResponse = Schemas["WorkflowEventResponse"];

export type WorkflowEventListResponse = Schemas["WorkflowEventListResponse"];

export type AnnualizedIncomeScheduleIncome = Schemas["AnnualizedIncomeScheduleIncome"];

export type AnnualizedIncomeScheduleHolding = Schemas["AnnualizedIncomeScheduleHolding"];

export type AnnualizedIncomeScheduleNetWorthTreatment = Schemas["AnnualizedIncomeScheduleNetWorthTreatment"];

export type AnnualizedIncomeScheduleResponse = Schemas["AnnualizedIncomeScheduleResponse"];

export type AnnualizedIncomeResponse = Schemas["AnnualizedIncomeResponse"];

export interface RestrictedHolding {
  ticker: string;
  quantity: DecimalValue;
  vesting_schedule?: string | null;
  unlock_date?: string | null;
  fair_value: MoneyValue;
  currency: string;
}

export type ValuationComponentsResponse = Schemas["ValuationComponentsResponse"];

export type ReconciliationStatsResponse = Schemas["ReconciliationStatsResponse"];

export interface UnmatchedTransactionsResponse {
  items: BankStatementTransactionSummary[];
  total: number;
}

export interface TrendPoint {
  period_start: string;
  period_end: string;
  amount: MoneyValue;
}

export interface TrendResponse {
  account_id: string;
  currency: string;
  period: string;
  points: TrendPoint[];
}

export type NetWorthRange = "1M" | "3M" | "6M" | "1Y" | "All";

export type NetWorthTimeSeriesPoint = Schemas["NetWorthTimeSeriesPoint"];

export type NetWorthTimeSeriesResponse = Schemas["NetWorthTimeSeriesResponse"];

export type NetWorthAllocationSourceLine = Schemas["NetWorthAllocationSourceLine"];

export interface NetWorthAllocationRow {
  asset_class: string;
  liquidity_class: string;
  source_currency: string;
  value: MoneyValue;
  percentage_of_net_worth: MoneyValue | null;
  source_line_count: number;
  source_lines: NetWorthAllocationSourceLine[];
}

export interface NetWorthAllocationResponse {
  as_of_date: string;
  currency: string;
  include_restricted: boolean;
  total_assets: MoneyValue;
  total_liabilities: MoneyValue;
  net_worth: MoneyValue;
  rows: NetWorthAllocationRow[];
}

export interface ReconciliationMatchResponse {
  id: string;
  bank_txn_id: string;
  journal_entry_ids: string[];
  match_score: number;
  score_breakdown: Record<string, number>;
  status:
    | "auto_accepted"
    | "pending_review"
    | "accepted"
    | "rejected"
    | "superseded";
  transaction?: BankStatementTransactionSummary | null;
  entries: JournalEntrySummary[];
}

export interface ReconciliationMatchListResponse {
  items: ReconciliationMatchResponse[];
  total: number;
}

export interface ManagedPosition {
  id: string;
  user_id: string;
  account_id: string;
  asset_identifier: string;
  quantity: string;
  cost_basis: string;
  acquisition_date: string;
  disposal_date?: string | null;
  status: "active" | "disposed";
  currency: string;
  position_metadata?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  account_name?: string | null;
}

export interface ManagedPositionListResponse {
  items: ManagedPosition[];
  total: number;
}

export interface ReconcilePositionsResponse {
  message: string;
  created: number;
  updated: number;
  disposed: number;
  skipped: number;
  skipped_assets: string[];
}

export type ManualValuationComponentType =
  | "property_value"
  | "mortgage_balance"
  | "cpf_balance"
  | "long_term_savings"
  | "tax_payable"
  | "tax_refund"
  | "insurance_cash_value"
  | "esop"
  | "rsu"
  | "stock_options"
  | "other_asset"
  | "other_liability";

export type ManualValuationLiquidityClass =
  | "liquid"
  | "restricted"
  | "illiquid"
  | "liability";

// Structured evidence basis for a manual valuation (EPIC-011 AC11.9.5/#706).
// Mirrors the backend `ManualValuationBasis` enum.
export type ManualValuationBasis =
  | "market_appraisal"
  | "broker_statement"
  | "employer_grant_document"
  | "bank_statement"
  | "government_statement"
  | "insurer_statement"
  | "self_estimate";

export type ManualValuationSource =
  | "manual"
  | "broker_portal"
  | "bank_portal"
  | "cpf_portal"
  | "tax_portal"
  | "insurer_portal"
  | "employer_portal"
  | "property_valuation"
  | "other_document";

export interface ManualValuationSnapshot {
  id: string;
  user_id: string;
  component_type: ManualValuationComponentType;
  liquidity_class: ManualValuationLiquidityClass;
  as_of_date: string;
  value: string;
  currency: string;
  source: string;
  valuation_basis?: ManualValuationBasis | null;
  notes?: string | null;
  recurrence_days?: number | null;
  reminder_date?: string | null;
  provenance: DataProvenance;
  created_at: string;
  updated_at: string;
}

export interface ManualValuationSnapshotListResponse {
  items: ManualValuationSnapshot[];
  total: number;
}

// ── Portfolio Management (EPIC-017) ──────────────────────────────────

export interface PortfolioHolding {
  id: string;
  user_id: string;
  account_id: string;
  asset_identifier: string;
  quantity: string;
  cost_basis: string;
  market_value: string;
  unrealized_pnl: string;
  unrealized_pnl_percent: string;
  currency: string;
  acquisition_date: string;
  disposal_date?: string | null;
  status: "active" | "disposed";
  cost_basis_method?: "FIFO" | "LIFO" | "AvgCost" | null;
  account_name?: string | null;
  asset_type?: string | null;
  sector?: string | null;
  geography?: string | null;
  /** Normalized provenance when known; null when not safely derivable (#888). */
  provenance?: DataProvenance | null;
}

export interface PortfolioSummaryResponse {
  total_market_value: string;
  total_cost_basis: string;
  total_unrealized_pnl: string;
  total_unrealized_pnl_percent: string;
  total_realized_pnl: string;
  total_realized_pnl_percent: string;
  net_pnl: string;
  net_pnl_percent: string;
  holdings_count: number;
  active_positions_count: number;
  disposed_positions_count: number;
  currency: string;
  realized_pnl_ytd: string;
  dividend_income_ytd: string;
}

export interface DividendEvent {
  id: string;
  ex_date: string;
  pay_date: string;
  amount: string;
  currency: string;
  reinvested: boolean;
}

export interface RealizedLot {
  lot_id: string;
  acquired_date?: string | null;
  sold_date: string;
  quantity: string;
  basis: string;
  proceeds: string;
  gain_loss: string;
  holding_period?: number | null;
  currency: string;
}

export interface PerformanceMetrics {
  xirr: string;
  time_weighted_return: string;
  money_weighted_return: string;
}

export type InvestmentPerformanceHoldingRow = Schemas["InvestmentPerformanceHoldingRow"];

export type InvestmentPerformanceAllocationRow = Schemas["InvestmentPerformanceAllocationRow"];

export type InvestmentPerformanceDataFreshness = Schemas["InvestmentPerformanceDataFreshness"];

export interface InvestmentPerformanceReportSchedule {
  period_start: string;
  period_end: string;
  as_of_date: string;
  currency: string;
  xirr: string | null;
  time_weighted_return: string | null;
  money_weighted_return: string | null;
  realized_pnl: string;
  unrealized_pnl: string;
  dividend_income: string;
  dividend_yield: string | null;
  holdings: InvestmentPerformanceHoldingRow[];
  allocation: InvestmentPerformanceAllocationRow[];
  data_freshness: InvestmentPerformanceDataFreshness;
  source_links: string[];
  notes: string[];
}

export interface AllocationBreakdown {
  category: string;
  value: string;
  percentage: string;
  count: number;
}

export interface PriceUpdate {
  asset_identifier: string;
  price: string;
  currency: string;
  price_date: string;
}

export interface PriceUpdateResponse {
  updated_count: number;
  results: Array<{
    success: boolean;
    message: string;
    asset_identifier: string;
    price_date: string;
    price: string;
    currency: string;
    source: string;
    created_at?: string | null;
  }>;
}

export type ProcessingSummaryResponse = Schemas["ProcessingSummaryResponse"];

export type ProcessingPendingItem = Schemas["ProcessingPendingItem"];

export interface ProcessingPendingListResponse {
  items: ProcessingPendingItem[];
  total: number;
}

// ── Brokerage Import (EPIC-017 / statement import completion) ─────────────

export type BrokerageImportResponse = Schemas["BrokerageImportResponse"];

// ── North-Star confidence metric (EPIC-018 AC18.12 / #1003, #1055 PR4) ─────
//
// The single measurable expression of Axiom B's loop: the share of posted
// ledger facts that sit in the LOW confidence tier. Lower is better. Decimal
// proportions arrive as strings (e.g. "0.12500") to preserve precision.

export type ConfidenceMetricPoint = Schemas["ConfidenceMetricPoint"];

export interface ConfidenceMetricSnapshot extends ConfidenceMetricPoint {
  id: string;
  captured_at: string;
}

export type ConfidenceNorthStarResponse = Schemas["ConfidenceNorthStarResponse"];

export type CorrectionLoopReplayResponse = Schemas["CorrectionLoopReplayResponse"];

// ── User AI settings & session identity (EPIC-022 AC22.15 / #1010) ──────────
//
// Mirrors backend `UserAiSettingsResponse` / `UserAiSettingsUpdate`
// (apps/backend/src/schemas/user.py).

export interface UserAiSettings {
  enable_ai_reconciliation: boolean;
  enable_ai_classification: boolean;
}

export type UserAiSettingsUpdate = Schemas["UserAiSettingsUpdate"];

/**
 * Identity returned by `GET /api/auth/me`, consumed by `useSessionBootstrap`.
 *
 * Deliberately excludes the bearer `access_token` that the backend
 * `AuthResponse` carries: the frontend uses cookie-based auth and never
 * persists a token from this endpoint, so exposing it on the typed shape would
 * only invite misuse. This type is the non-secret identity subset only.
 */
export interface CurrentUser {
  id: string;
  email: string;
  name: string | null;
  created_at: string;
}

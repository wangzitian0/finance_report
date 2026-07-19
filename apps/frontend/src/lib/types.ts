/**
 * Shared Type Definitions
 */

import type { Schemas } from "./api-schema";

export type DecimalValue = string;
export type MoneyValue = DecimalValue;
export type DataProvenance = "imported" | "manual" | "derived";
export const MONEY_VALUE_CONTRACT = "decimal-string" as const;

/**
 * Single source of truth for the paginated list envelope returned by every
 * `GET /…` collection endpoint. Per-entity list responses derive from this
 * (`ListResponse<Account>`, …) instead of re-declaring `{ items; total }`.
 */
export interface ListResponse<T> {
  items: T[];
  total: number;
}

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

export type AccountListResponse = ListResponse<Account>;

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

export type JournalEntryListResponse = ListResponse<JournalEntry>;

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

export type BankStatementListResponse = ListResponse<BankStatement>;

export type ReportLine = Schemas["ReportLine"];

export type AccountLineageLine = Schemas["AccountLineageLine"];

export type AccountLineageResponse = Schemas["AccountLineageResponse"];

/**
 * The generated `fx_warnings`/`opening_balance_warnings` fields are typed as
 * a loose `{[key: string]: string}[]` dict (the backend's Pydantic schema
 * models the field as `list[dict[str, str]]`, not a precise shape) — this
 * richer type is what the presentation layer (`FxWarningBanner`) actually
 * relies on (`.type`, `.message`, `.from_currency`, …). Every report response
 * below overrides those two fields with `FxWarning[]` instead of taking the
 * generated dict shape as-is.
 */
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

export type BalanceSheetResponse = Omit<
  Schemas["BalanceSheetResponse"],
  "fx_warnings" | "opening_balance_warnings"
> & {
  fx_warnings?: FxWarning[];
  opening_balance_warnings?: FxWarning[];
};

export type IncomeStatementTrend = Schemas["IncomeStatementTrend"];

export type IncomeStatementResponse = Omit<Schemas["IncomeStatementResponse"], "fx_warnings"> & {
  fx_warnings?: FxWarning[];
};

export type CashFlowItem = Schemas["CashFlowItem"];

export type CashFlowSummary = Schemas["CashFlowSummary"];

export type CashFlowResponse = Omit<Schemas["CashFlowResponse"], "fx_warnings"> & {
  fx_warnings?: FxWarning[];
};

export type PersonalReportPackageSectionContract = Schemas["PersonalReportPackageSectionContract"];

export interface PersonalReportPackageContractResponse {
  package_id: string;
  version: string;
  period_semantics: Record<string, string>;
  supported_frameworks: string[];
  selected_framework_id?: string | null;
  sections: PersonalReportPackageSectionContract[];
  export_contract: {
    formats: string[];
    csv_columns: string[];
  };
}

export type PersonalReportPackageReadinessBlocker = Schemas["PersonalReportPackageReadinessBlocker"];

export interface PersonalReportPackageInputCoverage {
  manifest_decision_count: number;
  authoritative_input_count: number;
  unproven_input_count: number;
}

export interface PersonalReportPackageReadinessResponse {
  package_id: string;
  state: "ready" | "processing" | "blocked" | "draft" | "generated" | "stale";
  label: string;
  action_href: string;
  blocking_count: number;
  blockers: PersonalReportPackageReadinessBlocker[];
  input_coverage: PersonalReportPackageInputCoverage;
}

export type PersonalReportPackageDocumentLifecycle =
  Schemas["PersonalReportPackageDocumentLifecycle"];

export type PersonalReportPackageTraceManifestEntry =
  Schemas["PersonalReportPackageTraceManifestEntry"];

export type PersonalReportPackageStatementDispositionPolicy =
  Schemas["PersonalReportPackageStatementDispositionPolicy"];

export interface PersonalReportPackageSections {
  balance_sheet: BalanceSheetResponse;
  income_statement: IncomeStatementResponse;
  cash_flow: CashFlowResponse;
  investment_performance: InvestmentPerformanceReportSchedule;
  annualized_income_long_term: AnnualizedIncomeScheduleResponse;
  notes: PersonalReportPackageNotesResponse;
  traceability_appendix: PersonalReportPackageTraceabilityResponse;
}

/** The package renderer receives a complete document, never partial endpoint data. */
export interface PersonalReportPackageDocument {
  schema_version: "2";
  lifecycle: PersonalReportPackageDocumentLifecycle;
  snapshot_id: string | null;
  package_decision_id: string | null;
  generated_at: string;
  frozen_at: string | null;
  package_id: string;
  status: PersonalReportPackageSnapshotSummary["status"];
  context: {
    framework_id: Schemas["PersonalReportingFrameworkId"];
    start_date: string;
    end_date: string;
    as_of_date: string;
    currency: string;
  };
  contract: PersonalReportPackageContractResponse;
  readiness: PersonalReportPackageReadinessResponse;
  framework_policy: FrameworkPolicyResult;
  input_manifest: PersonalReportPackageTraceManifestEntry[];
  statement_disposition_policy?: PersonalReportPackageStatementDispositionPolicy | null;
  sections: PersonalReportPackageSections;
}

export interface PersonalReportPackageSnapshotResponse
  extends PersonalReportPackageSnapshotSummary {
  document: PersonalReportPackageDocument;
}

export type PersonalReportPackageSnapshotSummary = Schemas["PersonalReportPackageSnapshotSummary"];

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

// ── Stage-2 review queue (was hand-declared in components/review/stage2/types.ts, #1868 S5) ──

export type ConsistencyCheck = Schemas["ConsistencyCheckResponse"];

export type PendingMatch = Schemas["Stage2PendingMatch"];

export type Stage2Data = Schemas["Stage2ReviewQueueResponse"];

export type UnmatchedTransactionsResponse = ListResponse<BankStatementTransactionSummary>;

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
  // #1481/#1486: same opening-balance gate as the balance sheet.
  confidence_tier?: "TRUSTED" | "HIGH" | "MEDIUM" | "LOW" | null;
  opening_balance_warnings?: FxWarning[];
}

export interface ReconciliationMatchResponse {
  id: string;
  bank_txn_id: string;
  journal_entry_ids: string[];
  match_score: number;
  score_breakdown: Record<string, number | string>;
  status:
    | "auto_accepted"
    | "pending_review"
    | "accepted"
    | "rejected"
    | "superseded";
  transaction?: BankStatementTransactionSummary | null;
  entries: JournalEntrySummary[];
}

export type ReconciliationMatchListResponse = ListResponse<ReconciliationMatchResponse>;

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

export type ManagedPositionListResponse = ListResponse<ManagedPosition>;

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
  | "retirement_account"
  | "social_security_personal_account"
  | "long_term_benefit_asset"
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

export type ManualValuationSnapshotListResponse = ListResponse<ManualValuationSnapshot>;

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
  /** Reporting/base-currency view (same as `reporting_currency`). */
  currency: string;
  // #1482/#1487: native vs reporting are identically-named on both
  // /portfolio/holdings and /assets/positions, so the UI can show the native
  // denomination instead of depending on the endpoint-local `currency`.
  native_currency?: string;
  reporting_currency?: string;
  native_cost_basis?: string;
  reporting_cost_basis?: string;
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

/**
 * #1796: /portfolio/holdings responds in the repo-standard items+total wrapper;
 * `warnings` discloses snapshots excluded from the page (e.g. no reconciled
 * position as of the requested date) instead of omitting them silently.
 */
export interface HoldingsListResponse extends ListResponse<PortfolioHolding> {
  warnings: Record<string, string>[];
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

export type ProcessingPendingListResponse = ListResponse<ProcessingPendingItem>;

// ── Brokerage Import (EPIC-017 / statement import completion) ─────────────

export type BrokerageImportResponse = Schemas["BrokerageImportResponse"];

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

// Mirrors backend `BaseCurrencyResponse` / `BaseCurrencyUpdate`
// (apps/backend/src/schemas/app_config.py) — EPIC-012 AC12.39 / #1340.
export interface BaseCurrency {
  base_currency: string;
}

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

// ── LLM configuration (EPIC-023 PR4) ───────────────────────────────────────
//
// Frozen LLM contract surfaced to the frontend. Provider API keys are
// write-only and never returned by the backend, so `LlmProviderResponse`
// only carries `has_api_key`. Mirrors backend schemas in
// `apps/backend/src/schemas/llm.py`.

export type LlmModality = Schemas["Modality"];
export type LlmProtocolFamily = Schemas["ProtocolFamily"];
export type LlmReasoningEffort = Schemas["ReasoningEffort"];
export type LlmScene = Schemas["Scene"];

export type LlmConfigStatusResponse = Schemas["LlmConfigStatusResponse"];
export type LlmProviderResponse = Schemas["LlmProviderResponse"];
export type LlmProviderListResponse = Schemas["LlmProviderListResponse"];
export type LlmProviderCreate = Schemas["LlmProviderCreate"];
export type LlmModelResponse = Schemas["LlmModelResponse"];
export type LlmCatalogResponse = Schemas["LlmCatalogResponse"];
export type LlmSceneBindingItem = Schemas["LlmSceneBindingItem"];
export type LlmScenesResponse = Schemas["LlmScenesResponse"];
export type LlmScenesUpdate = Schemas["LlmScenesUpdate"];

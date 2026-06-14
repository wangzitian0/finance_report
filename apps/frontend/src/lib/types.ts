/**
 * Shared Type Definitions
 */

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

export interface JournalEntrySummary {
  id: string;
  entry_date: string;
  memo?: string | null;
  status: string;
  total_amount: MoneyValue;
}

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

export interface ReportLine {
  account_id: string;
  name: string;
  type: string;
  parent_id?: string | null;
  amount: MoneyValue;
  provenance?: DataProvenance | null;
}

export interface AccountLineageLine {
  journal_line_id: string;
  journal_entry_id: string;
  entry_date: string;
  memo: string;
  direction: string;
  original_amount: MoneyValue;
  original_currency: string;
  amount: MoneyValue;
}

export interface AccountLineageResponse {
  account_id: string;
  account_name: string;
  account_type: string;
  currency: string;
  as_of_date: string;
  start_date: string | null;
  total: MoneyValue;
  lines: AccountLineageLine[];
}

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

export interface IncomeStatementTrend {
  period_start: string;
  period_end: string;
  total_income: MoneyValue;
  total_expenses: MoneyValue;
  net_income: MoneyValue;
}

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

export interface CashFlowItem {
  category: string;
  subcategory: string;
  amount: MoneyValue;
  description: string | null;
  /** Account this line's movement belongs to, for report drill-down (#887). */
  account_id?: string | null;
}

export interface CashFlowSummary {
  operating_activities: MoneyValue;
  investing_activities: MoneyValue;
  financing_activities: MoneyValue;
  net_cash_flow: MoneyValue;
  beginning_cash: MoneyValue;
  ending_cash: MoneyValue;
}

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

export interface PersonalReportPackageSectionContract {
  section_id: string;
  label: string;
  owner_epic: string;
  period_type?: string;
  source_endpoint: string;
  status: string;
  required?: boolean;
  blocking_issue?: string | null;
  decimal_total_fields?: string[];
}

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

export interface PersonalReportPackageReadinessBlocker {
  code: string;
  label: string;
  severity: string;
  count: number;
  reason: string;
  action_href: string;
}

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

export interface PersonalReportPackageSnapshotSummary {
  id: string;
  package_id: string;
  status: "draft" | "trusted";
  framework_id: string;
  start_date: string;
  end_date: string;
  as_of_date: string;
  currency: string;
  readiness_state: string;
  is_latest: boolean;
  created_at?: string | null;
}

export interface PersonalReportPackageSnapshotResponse extends PersonalReportPackageSnapshotSummary {
  payload: PersonalReportPackageSnapshotPayload;
}

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

export interface PersonalReportPackageNote {
  note_id: string;
  label: string;
  owner_epic: string;
  basis: string;
  source_state: string;
  applies_to_sections: string[];
  disclosure: string;
}

export interface PersonalReportPackageNotesResponse {
  section_id: string;
  label: string;
  status: string;
  notes: PersonalReportPackageNote[];
  non_compliance_statement: string;
}

export interface PersonalReportPackageTraceabilityAnchor {
  state: string;
  source_types?: string[];
  entry_statuses?: string[];
  identifier_fields?: string[];
  identifiers?: string[];
  unavailable_reason?: string | null;
  details?: Array<Record<string, string | number | null>>;
}

export interface PersonalReportPackageTraceabilityLine {
  line_id: string;
  section_id: string;
  label: string;
  amount_field?: string | null;
  currency_field?: string | null;
  source_state: string;
  source_anchor: PersonalReportPackageTraceabilityAnchor;
  ledger_anchor: PersonalReportPackageTraceabilityAnchor;
  review_state: string;
  confidence_tier: string;
  source_classes?: string[];
  proof_level?: string;
  anchor_count?: number;
  blocker_codes?: string[];
}

export interface PersonalReportPackageCompletenessWarning {
  code: string;
  label: string;
  applies_to_sections: string[];
  state: string;
  remediation?: string | null;
}

export interface PersonalReportPackageTraceabilityResponse {
  section_id: string;
  label: string;
  status: string;
  lines: PersonalReportPackageTraceabilityLine[];
  completeness_warnings: PersonalReportPackageCompletenessWarning[];
}

export interface EvidenceLineageNode {
  id: string;
  node_kind: string;
  entity_type: string;
  entity_id: string;
  properties: Record<string, string | number | boolean | null>;
}

export interface EvidenceLineageEdge {
  id: string;
  from_node_id: string;
  to_node_id: string;
  relation: string;
  direction: "upstream" | "downstream";
  depth: number;
  properties: Record<string, string | number | boolean | null>;
}

export interface EvidenceLineageBlocker {
  code: string;
  message: string;
}

export interface EvidenceLineageResponse {
  anchor: EvidenceLineageNode | null;
  nodes: EvidenceLineageNode[];
  edges: EvidenceLineageEdge[];
  blockers: EvidenceLineageBlocker[];
  max_depth: number;
}

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

export interface WorkflowNextActionResponse {
  type: WorkflowNextActionType;
  count: number;
  href: string;
  label: string;
  summary: string;
}

export interface WorkflowReportReadinessResponse {
  state: WorkflowReportReadinessState;
  blocking_count: number;
  href: string;
}

export interface WorkflowEventCountsResponse {
  unread: number;
  action_required: number;
  blocked: number;
}

export interface WorkflowSessionSummaryResponse {
  id: string;
  status: WorkflowSessionStatus;
  title: string;
  summary: string;
  started_at: string;
  last_event_at?: string | null;
  source_count: number;
  report_href?: string | null;
  primary_state: WorkflowPrimaryState;
  report_readiness: WorkflowReportReadinessResponse;
  event_counts: WorkflowEventCountsResponse;
}

export interface WorkflowStatusResponse {
  primary_state: WorkflowPrimaryState;
  next_action: WorkflowNextActionResponse;
  report_readiness: WorkflowReportReadinessResponse;
  event_counts: WorkflowEventCountsResponse;
  active_session?: WorkflowSessionSummaryResponse | null;
}

export interface WorkflowEventResponse {
  id: string;
  user_id: string;
  session_id?: string | null;
  occurred_at: string;
  family: WorkflowEventFamily;
  severity: WorkflowEventSeverity;
  status: WorkflowEventStatus;
  title: string;
  summary: string;
  source_type: string;
  source_id: string;
  action_href: string;
  report_impact: WorkflowReportImpact;
  dedupe_key: string;
  created_at: string;
  updated_at: string;
}

export interface WorkflowEventListResponse {
  items: WorkflowEventResponse[];
  total: number;
  sessions: WorkflowSessionSummaryResponse[];
}

export interface AnnualizedIncomeScheduleIncome {
  annualized_salary: MoneyValue;
  annualized_bonus: MoneyValue;
  annualized_dividend: MoneyValue;
  annualized_total: MoneyValue;
  currency: string;
  calculation_basis: string;
}

export interface AnnualizedIncomeScheduleHolding {
  ticker: string;
  compensation_type: string;
  fair_value: MoneyValue;
  currency: string;
  valuation_basis: string;
  vesting_schedule?: string | null;
  unlock_date?: string | null;
  liquidity_class: string;
  net_worth_treatment: string;
}

export interface AnnualizedIncomeScheduleNetWorthTreatment {
  liquid_net_worth_default: string;
  restricted_wealth_basis: string;
  include_restricted_query: string;
  exclude_restricted_query: string;
}

export interface AnnualizedIncomeScheduleResponse {
  section_id: string;
  label: string;
  as_of_date: string;
  trailing_period_start: string;
  trailing_period_end: string;
  trailing_period_days: number;
  income: AnnualizedIncomeScheduleIncome;
  restricted_holdings: AnnualizedIncomeScheduleHolding[];
  restricted_fair_value_total: MoneyValue;
  restricted_fair_value_total_currency: string;
  net_worth_treatment: AnnualizedIncomeScheduleNetWorthTreatment;
  notes: string[];
}

export interface AnnualizedIncomeResponse {
  annualized_salary: MoneyValue;
  annualized_bonus: MoneyValue;
  annualized_dividend: MoneyValue;
  annualized_total: MoneyValue;
  currency: string;
  as_of: string;
}

export interface RestrictedHolding {
  ticker: string;
  quantity: DecimalValue;
  vesting_schedule?: string | null;
  unlock_date?: string | null;
  fair_value: MoneyValue;
  currency: string;
}

export interface ValuationComponentsResponse {
  items: unknown[];
  total_assets: MoneyValue;
  total_liabilities: MoneyValue;
  net_worth_delta: MoneyValue;
}

export interface ReconciliationStatsResponse {
  total_transactions: number;
  matched_transactions: number;
  unmatched_transactions: number;
  pending_review: number;
  auto_accepted: number;
  match_rate: number;
  score_distribution: Record<string, number>;
}

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

export interface NetWorthTimeSeriesPoint {
  date: string;
  total_assets: MoneyValue;
  total_liabilities: MoneyValue;
  net_worth: MoneyValue;
  currency: string;
}

export interface NetWorthTimeSeriesResponse {
  currency: string;
  granularity: "daily" | "monthly";
  points: NetWorthTimeSeriesPoint[];
}

export interface NetWorthAllocationSourceLine {
  source_type: string;
  source_id: string | null;
  label: string;
  value: MoneyValue;
  href: string | null;
}

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

export interface InvestmentPerformanceHoldingRow {
  asset_identifier: string;
  quantity: string;
  cost_basis: string;
  market_value: string;
  unrealized_pnl: string;
  realized_pnl: string;
  dividend_income: string;
  currency: string;
}

export interface InvestmentPerformanceAllocationRow {
  dimension: "sector" | "geography" | "asset_class" | string;
  category: string;
  value: string;
  percentage: string;
  count: number;
}

export interface InvestmentPerformanceDataFreshness {
  latest_price_date: string | null;
  market_data_provider: string | null;
  stale: boolean;
  stale_holdings: string[];
  manual_override_basis?: string | null;
}

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

export interface ProcessingSummaryResponse {
  pending_count: number;
  pending_total: string;
  current_balance: string;
  currency: string;
  oldest_pending_date: string | null;
}

export interface ProcessingPendingItem {
  entry_id: string;
  from_account: string;
  to_account: string;
  amount: string;
  currency: string;
  initiated_date: string;
  days_outstanding: number;
  description: string;
}

export interface ProcessingPendingListResponse {
  items: ProcessingPendingItem[];
  total: number;
}

// ── Brokerage Import (EPIC-017 / statement import completion) ─────────────

export interface BrokerageImportResponse {
  broker: string;
  parsed_positions: number;
  created_atomic_positions: number;
  existing_atomic_positions: number;
  reconcile_created: number;
  reconcile_updated: number;
  reconcile_disposed: number;
  skipped: number;
}

// ── North-Star confidence metric (EPIC-018 AC18.12 / #1003, #1055 PR4) ─────
//
// The single measurable expression of Axiom B's loop: the share of posted
// ledger facts that sit in the LOW confidence tier. Lower is better. Decimal
// proportions arrive as strings (e.g. "0.12500") to preserve precision.

export interface ConfidenceMetricPoint {
  total_count: number;
  low_confidence_count: number;
  low_confidence_proportion: DecimalValue;
  tier_breakdown: Record<string, number>;
}

export interface ConfidenceMetricSnapshot extends ConfidenceMetricPoint {
  id: string;
  captured_at: string;
}

export interface ConfidenceNorthStarResponse {
  current: ConfidenceMetricPoint;
  /** Recorded trend, newest-first. */
  series: ConfidenceMetricSnapshot[];
}

export interface CorrectionLoopReplayResponse {
  holdout_size: number;
  grounded: number;
  proportion_before: DecimalValue;
  proportion_after: DecimalValue;
  /** Whether the correction loop measurably lowered the held-out proportion. */
  reduced: boolean;
}

// ── User AI settings & session identity (EPIC-022 AC22.15 / #1010) ──────────
//
// Mirrors backend `UserAiSettingsResponse` / `UserAiSettingsUpdate`
// (apps/backend/src/schemas/user.py).

export interface UserAiSettings {
  enable_ai_reconciliation: boolean;
  enable_ai_classification: boolean;
}

export type UserAiSettingsUpdate = Partial<UserAiSettings>;

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

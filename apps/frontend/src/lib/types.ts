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

export type Account = Schemas["AccountResponse"];

export type AccountListResponse = ListResponse<Account>;

export type JournalLine = Schemas["JournalLineResponse"];

import {
  type BankStatementTransactionViewModel,
  type JournalEntryViewModel,
  toTransactionViewModel,
  toJournalEntryViewModel,
} from "./normalizers";
export {
  toTransactionViewModel,
  toJournalEntryViewModel,
};
export type {
  BankStatementTransactionViewModel,
  JournalEntryViewModel,
};

export type JournalEntry = JournalEntryViewModel;

export type JournalEntryResponse = Schemas["JournalEntryResponse"];

export type JournalEntrySummary = Schemas["JournalEntrySummary"];

export type JournalEntryListResponse = ListResponse<JournalEntry>;

export type BankStatementTransaction = BankStatementTransactionViewModel;

export type BankStatementTransactionResponse =
  Schemas["AtomicTransactionResponse"];

export type BankTransactionSummary = Schemas["BankTransactionSummary"];

export type BankStatementTransactionSummary = BankTransactionSummary;

export type BalanceValidationResult = Schemas["BalanceValidationResult"];

export interface BankStatementViewModel
  extends Omit<Schemas["BankStatementResponse"], "transactions"> {
  transactions: BankStatementTransaction[];
}

export type BankStatement = BankStatementViewModel;

export type BankStatementListResponse = ListResponse<BankStatement>;

export function normalizeBankStatement(
  statement: Schemas["BankStatementResponse"],
): BankStatement {
  return {
    ...statement,
    transactions: (statement.transactions ?? []).map((t) =>
      toTransactionViewModel(t),
    ),
  };
}

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

export type IncomeStatementResponse = Omit<
  Schemas["IncomeStatementResponse"],
  "fx_warnings"
> & {
  fx_warnings?: FxWarning[];
};

export type CashFlowItem = Schemas["CashFlowItem"];

export type CashFlowSummary = Schemas["CashFlowSummary"];

export type CashFlowResponse = Omit<
  Schemas["CashFlowResponse"],
  "fx_warnings"
> & {
  fx_warnings?: FxWarning[];
};

export type PersonalReportPackageSectionContract =
  Schemas["PersonalReportPackageSectionContract"];

export type PersonalReportPackageContractResponse =
  Schemas["PersonalReportPackageContractResponse"];

export type PersonalReportPackageReadinessBlocker =
  Schemas["PersonalReportPackageReadinessBlocker"];

export type PersonalReportPackageInputCoverage =
  Schemas["PersonalReportPackageInputCoverage"];

export type PersonalReportPackageReadinessResponse =
  Schemas["PersonalReportPackageReadinessResponse"];

export type PersonalReportPackageDocumentLifecycle =
  Schemas["PersonalReportPackageDocumentLifecycle"];
export type PersonalReportingFrameworkId =
  Schemas["PersonalReportingFrameworkId"];

export type PersonalReportPackageTraceManifestEntry =
  Schemas["PersonalReportPackageTraceManifestEntry"];

export type PersonalReportPackageStatementDispositionPolicy =
  Schemas["PersonalReportPackageStatementDispositionPolicy"];

export interface PersonalReportPackageSectionsViewModel {
  balance_sheet: BalanceSheetResponse;
  income_statement: IncomeStatementResponse;
  cash_flow: CashFlowResponse;
  investment_performance: InvestmentPerformanceReportSchedule;
  annualized_income_long_term: AnnualizedIncomeScheduleResponse;
  notes: PersonalReportPackageNotesResponse;
  traceability_appendix: PersonalReportPackageTraceabilityResponse;
}

export type PersonalReportPackageSections =
  PersonalReportPackageSectionsViewModel;

export interface PersonalReportPackageReadinessViewModel {
  package_id: string;
  state: Schemas["PersonalReportPackageReadinessState"];
  label: string;
  action_href: string;
  blocking_count: number;
  blockers: Schemas["PersonalReportPackageReadinessBlocker"][];
  input_coverage: Schemas["PersonalReportPackageInputCoverage"];
}

export interface PersonalReportPackageDocumentViewModel {
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
  readiness: PersonalReportPackageReadinessViewModel;
  framework_policy: Schemas["FrameworkPolicyResult"] & {
    decisions: (Schemas["FrameworkPolicyDecision"] & {
      evidence_anchors?: Schemas["FrameworkPolicyEvidenceAnchor"][];
    })[];
    gaps: (Schemas["FrameworkPolicyGap"] & {
      evidence_anchors?: Schemas["FrameworkPolicyEvidenceAnchor"][];
    })[];
  };
  input_manifest: PersonalReportPackageTraceManifestEntry[];
  statement_disposition_policy?: PersonalReportPackageStatementDispositionPolicy | null;
  sections: PersonalReportPackageSectionsViewModel;
}

export type PersonalReportPackageDocument =
  PersonalReportPackageDocumentViewModel;

export type PersonalReportPackageSnapshotSummary =
  Schemas["PersonalReportPackageSnapshotSummary"];

export interface PersonalReportPackageSnapshotViewModel
  extends PersonalReportPackageSnapshotSummary {
  created_at: string | null;
  document: PersonalReportPackageDocumentViewModel;
}

export type PersonalReportPackageSnapshotResponse =
  Schemas["PersonalReportPackageSnapshotResponse"];

export type AdvisorSuggestion = Schemas["AdvisorSuggestion"];

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

export interface ChatMetadata {
  grounded: boolean;
  citations: ChatCitation[];
  actions: ChatActionChip[];
}
export type ChatResponseMetadata = ChatMetadata;

export type ChatSuggestionsResponse = Schemas["ChatSuggestionsResponse"];

export type AiSuggestion = Schemas["AiSuggestionResponse"];
export type AiSuggestionListResponse = Schemas["AiSuggestionListResponse"];

export type PersonalReportPackageNote = Schemas["PersonalReportPackageNote"];

export type PersonalReportPackageNotesResponse =
  Schemas["PersonalReportPackageNotesResponse"];

export type PersonalReportPackageTraceabilityAnchor =
  Schemas["PersonalReportPackageTraceabilityAnchor"];

export type PersonalReportPackageTraceabilityLine =
  Schemas["PersonalReportPackageTraceabilityLine"];

export type PersonalReportPackageCompletenessWarning =
  Schemas["PersonalReportPackageCompletenessWarning"];

export type PersonalReportPackageTraceabilityResponse =
  Schemas["PersonalReportPackageTraceabilityResponse"];

export type EvidenceLineageNode = Schemas["EvidenceLineageNode"];

export type EvidenceLineageEdge = Schemas["EvidenceLineageEdge"];

export type EvidenceLineageBlocker = Schemas["EvidenceLineageBlocker"];

export type EvidenceLineageResponse = Schemas["EvidenceLineageResponse"];

export type FrameworkPolicyEvidenceAnchor =
  Schemas["FrameworkPolicyEvidenceAnchor"];

export type FrameworkPolicyDecision =
  Schemas["FrameworkPolicyDecision"];

export type FrameworkPolicyGap =
  Schemas["FrameworkPolicyGap"];

export type FrameworkPolicyResult =
  Schemas["FrameworkPolicyResult"];

export function normalizeFxWarningRows(
  rows: Array<Record<string, string>> | undefined,
): FxWarning[] {
  return (rows ?? []).map((row) => ({ ...row, type: row.type ?? "unknown" }));
}

export function normalizeAdvisorSuggestions(
  rows: Schemas["AdvisorSuggestion"][] | undefined,
): AdvisorSuggestion[] {
  return (rows ?? []).map((row) => ({
    ...row,
    source_refs: row.source_refs ?? [],
  }));
}

export function normalizePersonalReportPackageDocument(
  document: Schemas["PersonalReportPackageDocument"],
): PersonalReportPackageDocument {
  const coverage = document.readiness.input_coverage ?? {
    manifest_decision_count: 0,
    authoritative_input_count: 0,
    unproven_input_count: 0,
  };
  return {
    ...document,
    snapshot_id: document.snapshot_id ?? null,
    package_decision_id: document.package_decision_id ?? null,
    frozen_at: document.frozen_at ?? null,
    contract: {
      ...document.contract,
      supported_frameworks: document.contract.supported_frameworks ?? [],
    },
    readiness: {
      ...document.readiness,
      blockers: document.readiness.blockers ?? [],
      input_coverage: coverage,
    },
    framework_policy: {
      ...document.framework_policy,
      decisions: document.framework_policy.decisions.map((decision) => ({
        ...decision,
        evidence_anchors: decision.evidence_anchors ?? [],
      })),
      gaps: (document.framework_policy.gaps ?? []).map((gap) => ({
        ...gap,
        evidence_anchors: gap.evidence_anchors ?? [],
      })),
    },
    sections: {
      ...document.sections,
      balance_sheet: {
        ...document.sections.balance_sheet,
        fx_warnings: normalizeFxWarningRows(
          document.sections.balance_sheet.fx_warnings,
        ),
        opening_balance_warnings: normalizeFxWarningRows(
          document.sections.balance_sheet.opening_balance_warnings,
        ),
      },
      income_statement: {
        ...document.sections.income_statement,
        fx_warnings: normalizeFxWarningRows(
          document.sections.income_statement.fx_warnings,
        ),
      },
      cash_flow: {
        ...document.sections.cash_flow,
        fx_warnings: normalizeFxWarningRows(
          document.sections.cash_flow.fx_warnings,
        ),
      },
    },
  };
}

export function normalizePersonalReportPackageSnapshot(
  snapshot: Schemas["PersonalReportPackageSnapshotResponse"],
): PersonalReportPackageSnapshotViewModel {
  return {
    ...snapshot,
    created_at: snapshot.created_at ?? null,
    document: normalizePersonalReportPackageDocument(snapshot.document),
  };
}

export type WorkflowPrimaryState = Schemas["WorkflowPrimaryState"];

export type WorkflowNextActionType = Schemas["WorkflowNextActionType"];

export type WorkflowReportReadinessState =
  Schemas["WorkflowReportReadinessState"];

export type WorkflowEventFamily = Schemas["WorkflowEventFamily"];

export type WorkflowEventSeverity = Schemas["WorkflowEventSeverity"];

export type WorkflowEventStatus = Schemas["WorkflowEventStatus"];

export type WorkflowReportImpact = Schemas["WorkflowReportImpact"];

export type WorkflowSessionStatus = Schemas["WorkflowSessionStatus"];

export type WorkflowNextActionResponse = Schemas["WorkflowNextActionResponse"];

export type WorkflowReportReadinessResponse =
  Schemas["WorkflowReportReadinessResponse"];

export type WorkflowEventCountsResponse =
  Schemas["WorkflowEventCountsResponse"];

export type WorkflowSessionSummaryResponse =
  Schemas["WorkflowSessionSummaryResponse"];

export type WorkflowStatusResponse = Schemas["WorkflowStatusResponse"];

export type WorkflowEventResponse = Schemas["WorkflowEventResponse"];

export type WorkflowEventListResponse = Schemas["WorkflowEventListResponse"];

export type AnnualizedIncomeScheduleIncome =
  Schemas["AnnualizedIncomeScheduleIncome"];

export type AnnualizedIncomeScheduleHolding =
  Schemas["AnnualizedIncomeScheduleHolding"];

export type AnnualizedIncomeScheduleNetWorthTreatment =
  Schemas["AnnualizedIncomeScheduleNetWorthTreatment"];

export type AnnualizedIncomeScheduleResponse =
  Schemas["AnnualizedIncomeScheduleResponse"];

export type AnnualizedIncomeResponse = Schemas["AnnualizedIncomeResponse"];

export type RestrictedHolding = Schemas["RestrictedHoldingResponse"];

export type ValuationComponentsResponse =
  Schemas["ValuationComponentsResponse"];

export type ReconciliationStatsResponse =
  Schemas["ReconciliationStatsResponse"];

// ── Stage-2 review queue (was hand-declared in components/review/stage2/types.ts, #1868 S5) ──

export type ConsistencyCheck = Schemas["ConsistencyCheckResponse"];

export type PendingMatch = Schemas["Stage2PendingMatch"];

export type Stage2Data = Schemas["Stage2ReviewQueueResponse"];

export type UnmatchedTransactionsResponse =
  ListResponse<BankStatementTransactionSummary>;

export type AccountTrendPoint = Schemas["AccountTrendPoint"];
export type TrendPoint = AccountTrendPoint;

export type AccountTrendResponse = Schemas["AccountTrendResponse"];
export type TrendResponse = AccountTrendResponse;

export type NetWorthRange = "1M" | "3M" | "6M" | "1Y" | "All";

export type NetWorthTimeSeriesPoint = Schemas["NetWorthTimeSeriesPoint"];

export type NetWorthTimeSeriesResponse = Schemas["NetWorthTimeSeriesResponse"];

export type NetWorthAllocationSourceLine =
  Schemas["NetWorthAllocationSourceLine"];

export type NetWorthAllocationRow = Schemas["NetWorthAllocationRow"];

export type NetWorthAllocationResponse = Schemas["NetWorthAllocationResponse"];

export type ReconciliationMatchResponse =
  Schemas["ReconciliationMatchResponse"];

export type ReconciliationMatchListResponse =
  ListResponse<ReconciliationMatchResponse>;

export type ManagedPosition = Schemas["ManagedPositionResponse"];

export type ManagedPositionListResponse = ListResponse<ManagedPosition>;

export type ReconcilePositionsResponse = Schemas["ReconcilePositionsResponse"];

export type ManualValuationComponentType =
  Schemas["ManualValuationComponentType"];

export type ManualValuationLiquidityClass =
  Schemas["ManualValuationLiquidityClass"];

export type ManualValuationBasis = Schemas["ManualValuationBasis"];

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

export type ManualValuationSnapshot =
  Schemas["ManualValuationSnapshotResponse"];

export type ManualValuationSnapshotListResponse =
  ListResponse<ManualValuationSnapshot>;

// ── Portfolio Management (EPIC-017) ──────────────────────────────────

export type PortfolioHolding = Schemas["HoldingResponse"];

/**
 * #1796: /portfolio/holdings responds in the repo-standard items+total wrapper;
 * `warnings` discloses snapshots excluded from the page (e.g. no reconciled
 * position as of the requested date) instead of omitting them silently.
 */
export type HoldingsListResponse = Schemas["HoldingsListResponse"];

export type PortfolioSummaryDashboardResponse =
  Schemas["PortfolioSummaryDashboardResponse"];

export type PortfolioSummaryResponse = PortfolioSummaryDashboardResponse;

export type DividendEvent = Schemas["DividendEventResponse"];

export type RealizedLot = Schemas["RealizedLotResponse"];

export type PerformanceMetrics = Schemas["PerformanceMetricsResponse"];

export type InvestmentPerformanceHoldingRow =
  Schemas["InvestmentPerformanceHoldingRow"];

export type InvestmentPerformanceAllocationRow =
  Schemas["InvestmentPerformanceAllocationRow"];

export type InvestmentPerformanceDataFreshness =
  Schemas["InvestmentPerformanceDataFreshness"];

export type InvestmentPerformanceReportSchedule =
  Schemas["InvestmentPerformanceReportScheduleResponse"];

export type AllocationBreakdown = Schemas["AllocationBreakdownResponse"];

export type PriceUpdate = Schemas["PriceUpdateRequest"];

export type PriceUpdateBatchResponse = Schemas["PriceUpdateBatchResponse"];
export type PriceUpdateResponse = PriceUpdateBatchResponse;

export type ProcessingSummaryResponse = Schemas["ProcessingSummaryResponse"];

export type ProcessingPendingItem = Schemas["ProcessingPendingItem"];

export type ProcessingPendingListResponse = ListResponse<ProcessingPendingItem>;

// ── Brokerage Import (EPIC-017 / statement import completion) ─────────────

export type BrokerageImportResponse = Schemas["BrokerageImportResponse"];

export type CorrectionLoopReplayResponse =
  Schemas["CorrectionLoopReplayResponse"];

// ── User AI settings & session identity (EPIC-022 AC22.15 / #1010) ──────────
//
// Mirrors backend `UserAiSettingsResponse` / `UserAiSettingsUpdate`
// (apps/backend/src/schemas/user.py).

export type UserAiSettings = Schemas["UserAiSettingsResponse"];

export type UserAiSettingsUpdate = Schemas["UserAiSettingsUpdate"];

// Mirrors backend `BaseCurrencyResponse` / `BaseCurrencyUpdate`
// (apps/backend/src/schemas/app_config.py) — EPIC-012 AC12.39 / #1340.
export type BaseCurrency = Schemas["BaseCurrencyResponse"];

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

export type PingStateResponse = Schemas["PingStateResponse"];
export type PingState = PingStateResponse;

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

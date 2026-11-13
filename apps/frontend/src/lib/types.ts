import type { Schemas } from "./api-schema";
import {
  type BankStatementTransactionViewModel,
  type JournalEntryViewModel,
  toJournalEntryViewModel,
  toTransactionViewModel,
} from "./normalizers";

export { toJournalEntryViewModel, toTransactionViewModel };
export type { BankStatementTransactionViewModel, JournalEntryViewModel };

export type DecimalValue = string;
export type MoneyValue = DecimalValue;
export type DataProvenance = "imported" | "manual" | "derived";
export const MONEY_VALUE_CONTRACT = "decimal-string" as const;

export interface ListResponse<T> {
  items: T[];
  total: number;
}

export type Account = Schemas["AccountResponse"];
export type AccountListResponse = ListResponse<Account>;
export type JournalLine = Schemas["JournalLineResponse"];
export type JournalEntry = JournalEntryViewModel;
export type JournalEntryResponse = Schemas["JournalEntryResponse"];
export type JournalEntrySummary = Schemas["JournalEntrySummary"];
export type JournalEntryListResponse = ListResponse<JournalEntry>;
export type BankStatementTransaction = BankStatementTransactionViewModel;
export type BankTransactionSummary = Schemas["BankTransactionSummary"];
export type BalanceValidationResult = Schemas["BalanceValidationResult"];

export interface BankStatementViewModel
  extends Omit<Schemas["BankStatementResponse"], "transactions"> {
  transactions: BankStatementTransaction[];
}

export type BankStatement = BankStatementViewModel;
export type BankStatementListItem = Schemas["BankStatementListItemResponse"];
export type BankStatementListResponse = ListResponse<BankStatementListItem>;

export function normalizeBankStatement(
  statement: Schemas["BankStatementListItemResponse"] & {
    transactions?: readonly Schemas["AtomicTransactionResponse"][];
  },
): BankStatement {
  return {
    ...statement,
    transactions: (statement.transactions ?? []).map((t) => toTransactionViewModel(t)),
  };
}

export type ReportLine = Schemas["ReportLine"];
export type AccountLineageLine = Schemas["AccountLineageLine"];
export type AccountLineageResponse = Schemas["AccountLineageResponse"];

export interface FxWarning {
  type: string;
  message?: string;
  base_currency?: string;
  quote_currency?: string;
  rate_date?: string;
  from_currency?: string;
  to_currency?: string;
  date?: string;
  fallback_date?: string;
  source?: string;
  [key: string]: string | undefined;
}

type WithFxWarnings<T, Extra extends keyof T = never> = Omit<T, "fx_warnings" | Extra> & {
  fx_warnings?: FxWarning[];
} & ([Extra] extends [never] ? unknown : { [K in Extra]?: FxWarning[] });

export type BalanceSheetResponse = WithFxWarnings<
  Schemas["BalanceSheetResponse"],
  "opening_balance_warnings"
>;
export type IncomeStatementTrend = Schemas["IncomeStatementTrend"];
export type IncomeStatementResponse = WithFxWarnings<Schemas["IncomeStatementResponse"]>;
export type CashFlowItem = Schemas["CashFlowItem"];
export type CashFlowSummary = Schemas["CashFlowSummary"];
export type CashFlowResponse = WithFxWarnings<Schemas["CashFlowResponse"]>;
export type CashFlowLine = Schemas["CashFlowLine"];
export type CashFlowPreview = WithFxWarnings<Schemas["CashFlowPreview"]>;
export type CashFlowLineEvent = Schemas["CashFlowLineEvent"];
export type CashFlowLineEventsPage = Schemas["CashFlowLineEventsPage"];
export type PersonalReportPackageSectionContract = Schemas["PersonalReportPackageSectionContract"];
export type PersonalReportPackageContractResponse = Schemas["PersonalReportPackageContractResponse"];
export type PersonalReportPackageReadinessBlocker = Schemas["PersonalReportPackageReadinessBlocker"];
export type PersonalReportPackageInputCoverage = Schemas["PersonalReportPackageInputCoverage"];
export type PersonalReportPackageReadinessResponse = Schemas["PersonalReportPackageReadinessResponse"];
export type PersonalReportPackageDocumentLifecycle = Schemas["PersonalReportPackageDocumentLifecycle"];
export type PersonalReportingFrameworkId = Schemas["PersonalReportingFrameworkId"];
export type PersonalReportPackageTraceManifestEntry = Schemas["PersonalReportPackageTraceManifestEntry"];
export type PersonalReportPackageStatementDispositionPolicy =
  Schemas["PersonalReportPackageStatementDispositionPolicy"];

export type PackageCashFlow = Pick<
  CashFlowPreview,
  | "start_date"
  | "end_date"
  | "currency"
  | "summary"
  | "cash_bridge"
  | "proof_state"
  | "proof_reasons"
  | "fx_warnings"
>;

export interface PersonalReportPackageSectionsViewModel {
  balance_sheet: BalanceSheetResponse;
  income_statement: IncomeStatementResponse;
  cash_flow: PackageCashFlow;
  investment_performance: InvestmentPerformanceReportSchedule;
  annualized_income_long_term: AnnualizedIncomeScheduleResponse;
  notes: PersonalReportPackageNotesResponse;
  traceability_appendix: PersonalReportPackageTraceabilitySummary;
}

export type PersonalReportPackageSections = PersonalReportPackageSectionsViewModel;

export interface PersonalReportPackageFrozenEvidence {
  snapshot_id: string;
  traceability_appendix: PersonalReportPackageTraceabilityResponse;
  input_manifest: PersonalReportPackageTraceManifestEntry[];
  framework_policy_decisions: Schemas["FrameworkPolicyDecision"][];
}

export interface PersonalReportPackageReadinessViewModel
  extends Omit<Schemas["PersonalReportPackageReadinessResponse"], "blockers" | "input_coverage"> {
  blockers: Schemas["PersonalReportPackageReadinessBlocker"][];
  input_coverage: Schemas["PersonalReportPackageInputCoverage"];
}

export interface PackageFrameworkPolicy
  extends Omit<Schemas["FrameworkPolicyPreview"], "decisions" | "gaps"> {
  decisions: (Schemas["FrameworkPolicyDecision"] & {
    evidence_anchors?: Schemas["FrameworkPolicyEvidenceAnchor"][];
  })[];
  gaps: (Schemas["FrameworkPolicyGap"] & {
    evidence_anchors?: Schemas["FrameworkPolicyEvidenceAnchor"][];
  })[];
}

export const PACKAGE_POLICY_PREVIEW_DECISIONS = 25;

export function evidenceReferences(
  items: readonly { evidence_anchors?: readonly Schemas["FrameworkPolicyEvidenceAnchor"][] }[],
): string[] {
  const refs = items
    .flatMap((item) => item.evidence_anchors ?? [])
    .filter((a) => a.anchor_type && a.source_id)
    .map((a) => `${a.anchor_type}:${a.source_id}`);
  return Array.from(new Set(refs)).sort();
}

export interface PersonalReportPackageDocumentViewModel
  extends Omit<
    Schemas["PersonalReportPackageDocument"],
    | "snapshot_id"
    | "package_decision_id"
    | "frozen_at"
    | "readiness"
    | "framework_policy"
    | "sections"
    | "input_manifest"
  > {
  snapshot_id: string | null;
  package_decision_id: string | null;
  frozen_at: string | null;
  readiness: PersonalReportPackageReadinessViewModel;
  framework_policy: PackageFrameworkPolicy;
  sections: PersonalReportPackageSectionsViewModel;
  frozen_evidence: PersonalReportPackageFrozenEvidence | null;
}

export type PersonalReportPackageDocument = PersonalReportPackageDocumentViewModel;
export type PersonalReportPackageSnapshotSummary = Schemas["PersonalReportPackageSnapshotSummary"];

export interface PersonalReportPackageSnapshotViewModel
  extends PersonalReportPackageSnapshotSummary {
  created_at: string | null;
  document: PersonalReportPackageDocumentViewModel;
}

export type PersonalReportPackageSnapshotResponse = Schemas["PersonalReportPackageSnapshotResponse"];
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

export interface ChatResponseMetadata {
  grounded: boolean;
  citations: ChatCitation[];
  actions: ChatActionChip[];
}

export type ChatSuggestionsResponse = Schemas["ChatSuggestionsResponse"];
export type AiSuggestion = Schemas["AiSuggestionResponse"];
export type AiSuggestionListResponse = Schemas["AiSuggestionListResponse"];
export type PersonalReportPackageNote = Schemas["PersonalReportPackageNote"];
export type PersonalReportPackageNotesResponse = Schemas["PersonalReportPackageNotesResponse"];
export type PersonalReportPackageTraceabilityAnchor = Schemas["PersonalReportPackageTraceabilityAnchor"];
export type PersonalReportPackageCompletenessWarning = Schemas["PersonalReportPackageCompletenessWarning"];
export type PersonalReportPackageTraceabilityResponse = Schemas["PersonalReportPackageTraceabilityResponse"];
export type PersonalReportPackageTraceabilityAnchorName = Schemas["PersonalReportPackageTraceabilityAnchorName"];
export type PersonalReportPackageTraceabilityAnchorSummary =
  Schemas["PersonalReportPackageTraceabilityAnchorSummary"];
export type PersonalReportPackageTraceabilityLineSummary = Schemas["PersonalReportPackageTraceabilityLineSummary"];
export type PersonalReportPackageTraceabilitySummary = Schemas["PersonalReportPackageTraceabilitySummaryResponse"];
export type PersonalReportPackagePreview = Schemas["PersonalReportPackagePreview"];
export type PersonalReportPackageLineDetailsPage = Schemas["PersonalReportPackageLineDetailsPage"];
export type PersonalReportPackageTraceabilityDetail =
  NonNullable<PersonalReportPackageLineDetailsPage["details"]>[number];
export type PersonalReportPackageManifestEntriesPage = Schemas["PersonalReportPackageManifestEntriesPage"];
export type EvidenceLineageNode = Schemas["EvidenceLineageNode"];
export type EvidenceLineageEdge = Schemas["EvidenceLineageEdge"];
export type EvidenceLineageBlocker = Schemas["EvidenceLineageBlocker"];
export type EvidenceLineageResponse = Schemas["EvidenceLineageResponse"];
export type FrameworkPolicyEvidenceAnchor = Schemas["FrameworkPolicyEvidenceAnchor"];
export type FrameworkPolicyDecision = Schemas["FrameworkPolicyDecision"];
export type FrameworkPolicyGap = Schemas["FrameworkPolicyGap"];
export type FrameworkPolicyResult = Schemas["FrameworkPolicyResult"];
export type PersonalReportPackagePolicyDecisionsPage = Schemas["PersonalReportPackagePolicyDecisionsPage"];

export function normalizeFxWarningRows(rows: Array<Record<string, string>> | undefined): FxWarning[] {
  return (rows ?? []).map((row) => ({ ...row, type: row.type ?? "unknown" }));
}

export function normalizeAdvisorSuggestions(
  rows: Schemas["AdvisorSuggestion"][] | undefined,
): AdvisorSuggestion[] {
  return (rows ?? []).map((row) => ({ ...row, source_refs: row.source_refs ?? [] }));
}

function summarizeTraceabilityAnchor(
  anchor: PersonalReportPackageTraceabilityAnchor,
): PersonalReportPackageTraceabilityAnchorSummary {
  const { details, ...rest } = anchor;
  return {
    ...rest,
    source_types: anchor.source_types ?? [],
    entry_statuses: anchor.entry_statuses ?? [],
    identifier_fields: anchor.identifier_fields ?? [],
    unavailable_reason: anchor.unavailable_reason ?? null,
    detail_count: (details ?? []).length,
  };
}

function summarizeTraceabilityAppendix(
  appendix: PersonalReportPackageTraceabilityResponse,
): PersonalReportPackageTraceabilitySummary {
  return {
    ...appendix,
    lines: appendix.lines.map(({ source_anchor, ledger_anchor, ...line }) => ({
      ...line,
      amount_field: line.amount_field ?? null,
      currency_field: line.currency_field ?? null,
      source_anchor: summarizeTraceabilityAnchor(source_anchor),
      ledger_anchor: summarizeTraceabilityAnchor(ledger_anchor),
      anchor_count: line.anchor_count ?? 0,
      blocker_codes: line.blocker_codes ?? [],
    })),
  };
}

export function normalizePersonalReportPackageDocument(
  document: Schemas["PersonalReportPackageDocument"],
): PersonalReportPackageDocument {
  const snapshotId = document.snapshot_id ?? null;
  const { decisions, gaps = [] } = document.framework_policy;
  return normalizePackagePayload(document, {
    snapshot_id: snapshotId,
    package_decision_id: document.package_decision_id ?? null,
    frozen_at: document.frozen_at ?? null,
    traceability_appendix: summarizeTraceabilityAppendix(document.sections.traceability_appendix),
    policy_counts: {
      decision_count: decisions.length,
      evidence_reference_count: evidenceReferences([...decisions, ...gaps]).length,
    },
    frozen_evidence:
      snapshotId && document.lifecycle === "frozen"
        ? {
            snapshot_id: snapshotId,
            traceability_appendix: document.sections.traceability_appendix,
            input_manifest: document.input_manifest,
            framework_policy_decisions: decisions,
          }
        : null,
  });
}

export function normalizePersonalReportPackagePreview(
  preview: PersonalReportPackagePreview,
): PersonalReportPackageDocument {
  const { decision_count, evidence_reference_count } = preview.framework_policy;
  return normalizePackagePayload(preview, {
    snapshot_id: null,
    package_decision_id: null,
    frozen_at: null,
    traceability_appendix: preview.sections.traceability_appendix,
    policy_counts: { decision_count, evidence_reference_count },
    frozen_evidence: null,
  });
}

function normalizePackagePayload(
  document: Schemas["PersonalReportPackageDocument"] | PersonalReportPackagePreview,
  identity: {
    snapshot_id: string | null;
    package_decision_id: string | null;
    frozen_at: string | null;
    traceability_appendix: PersonalReportPackageTraceabilitySummary;
    policy_counts: { decision_count: number; evidence_reference_count: number };
    frozen_evidence: PersonalReportPackageFrozenEvidence | null;
  },
): PersonalReportPackageDocument {
  const { balance_sheet, income_statement, cash_flow } = document.sections;
  const withAnchors = <T extends { evidence_anchors?: Schemas["FrameworkPolicyEvidenceAnchor"][] }>(
    rows: readonly T[],
  ) => rows.map((row) => ({ ...row, evidence_anchors: row.evidence_anchors ?? [] }));
  const { input_manifest: _unused, ...docBase } = document as Schemas["PersonalReportPackageDocument"] & {
    input_manifest?: unknown;
  };
  void _unused;
  return {
    ...docBase,
    snapshot_id: identity.snapshot_id,
    package_decision_id: identity.package_decision_id,
    frozen_at: identity.frozen_at,
    statement_disposition_policy: document.statement_disposition_policy ?? null,
    frozen_evidence: identity.frozen_evidence,
    contract: {
      ...document.contract,
      supported_frameworks: document.contract.supported_frameworks ?? [],
    },
    readiness: {
      ...document.readiness,
      blockers: document.readiness.blockers ?? [],
      input_coverage: document.readiness.input_coverage ?? {
        manifest_decision_count: 0,
        authoritative_input_count: 0,
        unproven_input_count: 0,
      },
    },
    framework_policy: {
      ...document.framework_policy,
      ...identity.policy_counts,
      decisions: withAnchors(document.framework_policy.decisions.slice(0, PACKAGE_POLICY_PREVIEW_DECISIONS)),
      gaps: withAnchors(document.framework_policy.gaps ?? []),
    },
    sections: {
      ...document.sections,
      balance_sheet: {
        ...balance_sheet,
        fx_warnings: normalizeFxWarningRows(balance_sheet.fx_warnings),
        opening_balance_warnings: normalizeFxWarningRows(balance_sheet.opening_balance_warnings),
      },
      income_statement: {
        ...income_statement,
        fx_warnings: normalizeFxWarningRows(income_statement.fx_warnings),
      },
      cash_flow: {
        start_date: cash_flow.start_date,
        end_date: cash_flow.end_date,
        currency: cash_flow.currency,
        summary: cash_flow.summary,
        cash_bridge: cash_flow.cash_bridge,
        proof_state: cash_flow.proof_state,
        proof_reasons: cash_flow.proof_reasons,
        fx_warnings: normalizeFxWarningRows(cash_flow.fx_warnings),
      },
      traceability_appendix: identity.traceability_appendix,
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
export type WorkflowReportReadinessState = Schemas["WorkflowReportReadinessState"];
export type WorkflowEventFamily = Schemas["WorkflowEventFamily"];
export type WorkflowEventSeverity = Schemas["WorkflowEventSeverity"];
export type WorkflowEventStatus = Schemas["WorkflowEventStatus"];
export type WorkflowReportImpact = Schemas["WorkflowReportImpact"];
export type WorkflowSessionStatus = Schemas["WorkflowSessionStatus"];
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
export type ValuationComponentsResponse = Schemas["ValuationComponentsResponse"];
export type ReconciliationStatsResponse = Schemas["ReconciliationStatsResponse"];
export type ConsistencyCheck = Schemas["ConsistencyCheckResponse"];
export type PendingMatch = Schemas["Stage2PendingMatch"];
export type Stage2Data = Schemas["Stage2ReviewQueueResponse"];
export type UnmatchedTransactionsResponse = ListResponse<BankTransactionSummary>;
export type NetWorthTimeSeriesPoint = Schemas["NetWorthTimeSeriesPoint"];
export type NetWorthTimeSeriesResponse = Schemas["NetWorthTimeSeriesResponse"];
export type NetWorthAllocationSourceLine = Schemas["NetWorthAllocationSourceLine"];
export type NetWorthAllocationRow = Schemas["NetWorthAllocationRow"];
export type NetWorthAllocationResponse = Schemas["NetWorthAllocationResponse"];
export type ReconciliationMatchResponse = Schemas["ReconciliationMatchResponse"];
export type ReconciliationMatchListResponse = ListResponse<ReconciliationMatchResponse>;
export type ManagedPosition = Schemas["ManagedPositionResponse"];
export type ManagedPositionListResponse = ListResponse<ManagedPosition>;
export type ReconcilePositionsResponse = Schemas["ReconcilePositionsResponse"];
export type ManualValuationComponentType = Schemas["ManualValuationComponentType"];
export type ManualValuationLiquidityClass = Schemas["ManualValuationLiquidityClass"];
export type ManualValuationBasis = Schemas["ManualValuationBasis"];
export type ManualValuationSnapshot = Schemas["ManualValuationSnapshotResponse"];
export type ManualValuationSnapshotListResponse = ListResponse<ManualValuationSnapshot>;
export type PortfolioHolding = Schemas["HoldingResponse"];
export type HoldingsListResponse = Schemas["HoldingsListResponse"];
export type PortfolioSummaryDashboardResponse = Schemas["PortfolioSummaryDashboardResponse"];
export type DividendEvent = Schemas["DividendEventResponse"];
export type RealizedLot = Schemas["RealizedLotResponse"];
export type InvestmentPerformanceHoldingRow = Schemas["InvestmentPerformanceHoldingRow"];
export type InvestmentPerformanceAllocationRow = Schemas["InvestmentPerformanceAllocationRow"];
export type InvestmentPerformanceDataFreshness = Schemas["InvestmentPerformanceDataFreshness"];
export type InvestmentPerformanceReportSchedule = Schemas["InvestmentPerformanceReportScheduleResponse"];
export type AllocationBreakdown = Schemas["AllocationBreakdownResponse"];
export type PriceUpdate = Schemas["PriceUpdateRequest"];
export type PriceUpdateBatchResponse = Schemas["PriceUpdateBatchResponse"];
export type ProcessingSummaryResponse = Schemas["ProcessingSummaryResponse"];
export type ProcessingPendingItem = Schemas["ProcessingPendingItem"];
export type ProcessingPendingListResponse = ListResponse<ProcessingPendingItem>;
export type BrokerageImportResponse = Schemas["BrokerageImportResponse"];
export type StatementRun = Schemas["StatementRunRecord"];
export type StatementRunHints = Schemas["RunHints"];
export type CorrectionLoopReplayResponse = Schemas["CorrectionLoopReplayResponse"];
export type UserAiSettings = Schemas["UserAiSettingsResponse"];
export type UserAiSettingsUpdate = Schemas["UserAiSettingsUpdate"];
export type BaseCurrency = Schemas["BaseCurrencyResponse"];
export type PingStateResponse = Schemas["PingStateResponse"];
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
export type PersonalDataQualityHealthResponse = Schemas["PersonalDataQualityHealthResponse"];
export type QualityGrade = Schemas["QualityGrade"];
export type InvariantStatus = Schemas["InvariantStatus"];
export type MonthContinuityBucket = Schemas["MonthContinuityBucket"];
export type QualityActionItem = Schemas["QualityActionItem"];

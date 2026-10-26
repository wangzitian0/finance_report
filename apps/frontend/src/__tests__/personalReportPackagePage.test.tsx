import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PersonalReportPackageSections } from "@/lib/types";
import ReportsPage from "@/app/(main)/reports/page";
import { PackageSectionCards, renderCsv, renderSourceClasses } from "@/components/reports/package/shared";
import { personalReportPackageQuery } from "@/hooks/usePersonalReportPackage";
import { readReportFilters } from "@/hooks/useReportFilters";
import { track, ANALYTICS_EVENTS } from "@/lib/analytics";

import { setTestUrl } from "./helpers/nextNavigation";

vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);

vi.mock("@/hooks/useCurrencies", () => ({
  useCurrencies: () => ({ currencies: ["SGD", "USD"], loading: false }),
}));

vi.mock("@/hooks/useBaseCurrency", () => ({
  useBaseCurrency: () => ({ baseCurrency: "SGD", loading: false }),
}));

const mockedApiDownload = vi.fn();
const mockedApiFetch = vi.fn();

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  const { API_OPERATIONS } = await import("@/lib/api-operations");

  function compatibilityPath(operationId: string, request: any): string {
    const def = (API_OPERATIONS as Record<string, { method: string; path: string }>)[operationId];
    if (!def) return `/${operationId}`;
    let path = def.path.replace(/\{([^}]+)\}/g, (_placeholder, name: string) => {
      const val = request.path?.[name];
      if (val === undefined || val === null) throw new Error(`Missing OpenAPI path parameter: ${name}`);
      return encodeURIComponent(String(val));
    });
    if (request.query) {
      const query = new URLSearchParams();
      for (const [name, rawVal] of Object.entries(request.query)) {
        if (rawVal === undefined || rawVal === null) continue;
        for (const val of Array.isArray(rawVal) ? rawVal : [rawVal]) query.append(name, String(val));
      }
      const encoded = query.toString();
      if (encoded) path = `${path}?${encoded}`;
    }
    return path;
  }

  return {
    ...actual,
    apiOperation: vi.fn(async (operationId: any, ...args: any[]) => {
      const request = (args[0] ?? {}) as any;
      const path = compatibilityPath(operationId, request);
      const def = (API_OPERATIONS as Record<string, { method: string; path: string }>)[operationId];
      if (def?.method === "GET" && request.body === undefined && request.headers === undefined && request.signal === undefined) {
        return mockedApiFetch(path);
      }
      return mockedApiFetch(path, {
        method: def?.method ?? "POST",
        body: request.body === undefined ? undefined : JSON.stringify(request.body),
        headers: request.headers,
        signal: request.signal,
      });
    }),
    apiOperationDownload: vi.fn(async (operationId: any, request: any) => {
      const path = compatibilityPath(operationId, request);
      const def = (API_OPERATIONS as Record<string, { method: string; path: string }>)[operationId];
      if (def?.method === "GET" && request.headers === undefined && request.signal === undefined) {
        return mockedApiDownload(path);
      }
      return mockedApiDownload(path, { method: def?.method ?? "GET", headers: request.headers, signal: request.signal });
    }),
  };
});

vi.mock("@/lib/analytics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/analytics")>()),
  track: vi.fn(),
}));

const statementTxnId = "11111111-1111-4111-8111-111111111111";
const journalEntryId = "22222222-2222-4222-8222-222222222222";
const journalLineId = "33333333-3333-4333-8333-333333333333";
const uploadedDocumentId = "44444444-4444-4444-8444-444444444444";
const atomicTransactionId = "55555555-5555-4555-8555-555555555555";
const reportLineNodeId = "66666666-6666-4666-8666-666666666666";

// The Full package tab of /reports. The URL holds the period of the package.
const PersonalReportPackagePage = () => <ReportsPage />;
const renderPackagePage = () => render(<PersonalReportPackagePage />);

const contract = {
  package_id: "personal-financial-report-package",
  version: "1.0",
  period_semantics: {
    start_date: "required for period sections",
    end_date: "required for period sections",
    as_of_date: "required for point-in-time sections",
    currency: "ISO-4217 code; defaults to base currency when omitted",
    decimal_serialization: "string",
  },
  supported_frameworks: ["personal_us_gaap_like", "personal_hkfrs_like"],
  selected_framework_id: null,
  sections: [
    { section_id: "balance_sheet", label: "Balance Sheet", owner_epic: "EPIC-005", status: "ready" },
    { section_id: "income_statement", label: "Income Statement", owner_epic: "EPIC-005", status: "ready" },
    { section_id: "cash_flow", label: "Cash Flow", owner_epic: "EPIC-005", status: "ready" },
    { section_id: "investment_performance", label: "Investment Performance", owner_epic: "EPIC-017", status: "ready" },
    { section_id: "annualized_income_long_term", label: "Annualized Income & Long-Term Compensation", owner_epic: "EPIC-011", status: "ready" },
    { section_id: "notes", label: "Notes & Disclosures", owner_epic: "EPIC-005", status: "ready" },
    { section_id: "traceability_appendix", label: "Traceability Appendix", owner_epic: "EPIC-018", status: "ready" },
  ],
  export_contract: {
    formats: ["json", "csv"],
    csv_columns: [
      "package_id", "section_id", "line_id", "label", "amount", "currency",
      "source_state", "selected_framework_id", "framework_policy_result_id",
      "framework_policy_matrix_version", "evidence_bundle_references",
    ],
  },
};

const annualizedSchedule = {
  section_id: "annualized_income_long_term",
  label: "Annualized Income & Long-Term Compensation",
  as_of_date: "2026-05-20",
  trailing_period_start: "2025-05-20",
  trailing_period_end: "2026-05-20",
  trailing_period_days: 365,
  income: {
    annualized_salary: "120000.00",
    annualized_bonus: "15000.00",
    annualized_dividend: "2400.00",
    annualized_total: "137400.00",
    currency: "SGD",
    calculation_basis: "posted_or_reconciled_income_journal_lines_trailing_12_months",
  },
  restricted_holdings: [
    { ticker: "SHOP-RSU", compensation_type: "rsu", fair_value: "12500.00", currency: "SGD", valuation_basis: "manual_valuation_snapshot", vesting_schedule: "25% annual vesting", unlock_date: "2027-01-01", liquidity_class: "restricted", net_worth_treatment: "excluded_from_liquid_net_worth_by_default" },
  ],
  restricted_fair_value_total: "12500.00",
  restricted_fair_value_total_currency: "SGD",
  net_worth_treatment: {
    liquid_net_worth_default: "exclude_restricted_holdings",
    restricted_wealth_basis: "manual_valuation_snapshot_fair_value",
    include_restricted_query: "/api/reports/balance-sheet?include_restricted=true",
    exclude_restricted_query: "/api/reports/balance-sheet?include_restricted=false",
  },
  notes: ["Personal management report only; not tax advice.", "Restricted holdings are excluded from liquid net worth by default."],
};

const readiness = {
  package_id: "personal-financial-report-package",
  state: "blocked",
  label: "Blocked",
  action_href: "/review",
  blocking_count: 2,
  input_coverage: { manifest_decision_count: 1, authoritative_input_count: 4, unproven_input_count: 2 },
  blockers: [
    { code: "pending_review", label: "Pending source review", severity: "blocking", count: 1, reason: "Statement review must be completed before the package can be marked ready.", action_href: "/review" },
    { code: "balance_mismatch", label: "Balance validation mismatch", severity: "blocking", count: 1, reason: "Opening and closing balances must validate before report totals are trusted.", action_href: "/review" },
  ],
  generated_at: null,
  stale_since: null,
};

const frameworkPolicy = {
  result_id: "policy-result:personal_us_gaap_like:2025-05-20:2026-05-20:fixture",
  framework_id: "personal_us_gaap_like",
  matrix_version: "1.0",
  report_period_start: "2025-05-20",
  report_period_end: "2026-05-20",
  generated_at: "2026-05-20",
  required_statements: ["balance_sheet", "income_statement", "cash_flow", "notes", "traceability_appendix"],
  decisions: [
    {
      domain: "listed_security",
      recognition: "Recognize listed securities when brokerage evidence confirms ownership.",
      measurement: "Measure at quoted fair value when market data is fresh.",
      classification: "Marketable investment asset.",
      presentation: "US-like balance sheet marketable securities with unrealized gain note discipline.",
      disclosure: "Disclose price source and stale price blocker.",
      line_mappings: { balance_sheet: "assets.marketable_securities", income_statement: "income.unrealized_investment_gain_loss", notes: "notes.us_like_market_price_basis" },
      evidence_anchors: [
        { anchor_id: "atomic_position:abc", anchor_type: "atomic_position", source_system: "atomic_positions", source_id: "abc", description: "Brokerage holding" },
        { anchor_id: "market_price:def", anchor_type: "market_price", source_system: "stock_price", source_id: "def", description: "Synced market price" },
      ],
      provenance: "deterministic_matrix",
      review_state: "accepted",
      policy_field_name: "framework_policy_decision",
      accepted_value: "listed_security",
    },
  ],
  gaps: [
    {
      code: "unsupported_policy_domain",
      fact_id: "atomic_position:private-token",
      domain: "unsupported",
      instrument_type: "other",
      blocker: true,
      reason: "No deterministic v1 framework policy rule exists.",
      remediation: "Add an explicit reviewed policy rule before trusted output.",
      evidence_anchors: [{ anchor_id: "atomic_position:private-token", anchor_type: "atomic_position", source_system: "atomic_positions", source_id: "private-token", description: "Unsupported private token holding" }],
    },
  ],
};

const packageNotes = {
  section_id: "notes",
  label: "Notes & Disclosures",
  status: "ready",
  non_compliance_statement: "This personal management report is not a regulated filing, not legal advice, and not tax advice.",
  notes: [
    { note_id: "basis-of-preparation", label: "Basis of Preparation", owner_epic: "EPIC-005", basis: "personal_management_report_package_contract", source_state: "package_contract", applies_to_sections: ["balance_sheet", "income_statement"], disclosure: "The package assembles personal finance statements and schedules for management use." },
    { note_id: "valuation-basis", label: "Valuation Basis", owner_epic: "EPIC-011", basis: "manual_valuation_component_rules", source_state: "manual_valuation_snapshots", applies_to_sections: ["balance_sheet", "annualized_income_long_term"], disclosure: "Manual valuation snapshots supply restricted compensation values." },
  ],
};

// One detail per identifier, as the backend appendix builder writes it.
function detailsFor(identifiers: string[]) {
  return identifiers.map((identifier) => ({
    identifier,
    source_kind: identifier.split(":")[0],
    source_id: identifier.slice(identifier.indexOf(":") + 1),
    amount: identifier.startsWith("journal_line:") ? "120.00" : null,
    currency: identifier.startsWith("journal_line:") ? "SGD" : null,
    review_state: "current_authoritative_decision",
    decision_id: "77777777-7777-4777-8777-777777777777",
    reason_code: null,
  }));
}

const fullAnchor = <T extends { identifiers: string[] }>(anchor: T) => ({ ...anchor, details: detailsFor(anchor.identifiers) });
const withIdentifiers = <T extends { identifiers: string[] }>(anchor: T, identifiers: string[]) => ({ ...anchor, identifiers, details: detailsFor(identifiers) });

// The complete appendix: a frozen snapshot stores it with every identifier and detail.
const traceabilityAppendix = {
  section_id: "traceability_appendix",
  label: "Traceability Appendix",
  status: "ready",
  lines: [
    {
      line_id: "balance_sheet.total_assets",
      section_id: "balance_sheet",
      label: "Total Assets",
      amount_field: "total_assets",
      currency_field: "currency",
      source_state: "posted_reconciled_journal_lines_and_manual_valuations",
      source_anchor: fullAnchor({
        state: "available",
        source_types: ["bank_statement", "manual_valuation_snapshot"],
        identifier_fields: ["statement_transaction_ids", "manual_valuation_snapshot_ids"],
        identifiers: [`statement_transaction:${statementTxnId}`, "manual_valuation_snapshot:val-456"],
      }),
      ledger_anchor: fullAnchor({
        state: "available",
        entry_statuses: ["posted", "reconciled"],
        identifier_fields: ["journal_entry_ids", "journal_line_ids"],
        identifiers: [`journal_entry:${journalEntryId}`, `journal_line:${journalLineId}`],
      }),
      anchor_count: 4,
      blocker_codes: [],
    },
    {
      line_id: "notes.non_compliance_statement",
      section_id: "notes",
      label: "Package Non-Compliance Statement",
      amount_field: null,
      currency_field: null,
      source_state: "package_contract",
      source_anchor: fullAnchor({
        state: "available",
        source_types: ["package_contract"],
        identifier_fields: ["note_id"],
        identifiers: ["note:basis-of-preparation"],
      }),
      ledger_anchor: fullAnchor({ state: "not_applicable", entry_statuses: [], identifier_fields: [], identifiers: [] as string[] }),
      blocker_codes: ["static_contract_note"],
    },
  ],
  completeness_warnings: [
    { code: "manual_only_source", label: "Manual-only source coverage", applies_to_sections: ["balance_sheet", "annualized_income_long_term"], state: "explicit_manual_input_required" },
  ],
};

const balanceSheet = {
  as_of_date: "2026-05-20", currency: "SGD", assets: [], liabilities: [], equity: [],
  total_assets: "100000.00", total_liabilities: "35000.00", total_equity: "65000.00", net_income: "25400.00",
  unrealized_fx_gain_loss: "0.00", net_worth_adjustment_gain_loss: "0.00", equation_delta: "0.00", is_balanced: true,
};

const incomeStatement = {
  start_date: "2025-05-20", end_date: "2026-05-20", currency: "SGD", income: [], expenses: [],
  total_income: "137400.00", total_expenses: "112000.00", net_income: "25400.00", trends: [],
};

const cashFlow = {
  start_date: "2025-05-20", end_date: "2026-05-20", currency: "SGD", operating: [], investing: [], financing: [],
  summary: { operating_activities: "31000.00", investing_activities: "-6000.00", financing_activities: "-2500.00", net_cash_flow: "22500.00", beginning_cash: "30000.00", ending_cash: "52500.00" },
};

const investmentPerformance = {
  period_start: "2025-05-20", period_end: "2026-05-20", as_of_date: "2026-05-20", currency: "SGD",
  xirr: "0.10", time_weighted_return: "0.09", money_weighted_return: "0.10",
  realized_pnl: "1200.00", unrealized_pnl: "3400.00", dividend_income: "2400.00", dividend_yield: "0.02",
  holdings: [{ asset_identifier: "ACME", quantity: "10.00", cost_basis: "8000.00", market_value: "10000.00", unrealized_pnl: "2000.00", realized_pnl: "0.00", dividend_income: "240.00", currency: "SGD" }],
  allocation: [],
  data_freshness: { latest_price_date: "2026-05-20", market_data_provider: "fixture", stale: false, stale_holdings: [], manual_override_basis: null },
  source_links: ["source_document:brokerage-1"],
  notes: [],
};

function packageDocument(
  readinessPayload = readiness,
  policyPayload = frameworkPolicy,
  traceabilityPayload: unknown = traceabilityAppendix,
  lifecycle: "preview" | "frozen" = "preview",
  snapshotId: string | null = null,
) {
  return {
    schema_version: "2" as const,
    lifecycle,
    snapshot_id: snapshotId,
    package_decision_id: lifecycle === "frozen" ? "88888888-8888-4888-8888-888888888888" : null,
    generated_at: "2026-05-20T12:00:00Z",
    frozen_at: lifecycle === "frozen" ? "2026-05-20T12:00:00Z" : null,
    package_id: "personal-financial-report-package",
    status: readinessPayload.blocking_count === 0 ? "trusted" : "draft",
    context: { framework_id: policyPayload.framework_id, start_date: "2025-05-20", end_date: "2026-05-20", as_of_date: "2026-05-20", currency: "SGD" },
    contract: { ...contract, selected_framework_id: policyPayload.framework_id },
    readiness: readinessPayload,
    framework_policy: policyPayload,
    input_manifest: [
      {
        decision_id: "77777777-7777-4777-8777-777777777777",
        input_refs: [`journal_entry:${journalEntryId}`],
        target_kind: "journal_command",
        target_id: `statement-transaction:${statementTxnId}`,
        target_version: "fixture-v1",
        assertion_kind: "promotion",
        assertion_id: "reviewed_statement_posting",
        assertion_version: "1",
        authority_tier: "CODE-ONLY",
      },
    ],
    sections: {
      balance_sheet: balanceSheet,
      income_statement: incomeStatement,
      cash_flow: cashFlow,
      investment_performance: investmentPerformance,
      annualized_income_long_term: annualizedSchedule,
      notes: packageNotes,
      traceability_appendix: traceabilityPayload,
    },
  };
}

// The wire shape of `GET /reports/package` (#2583 S8): per-line detail counts, no identifiers,
// no details and no input manifest entries.
function previewAnchor(anchor: Record<string, unknown>) {
  const { identifiers: _identifiers, details, ...summary } = anchor;
  return { ...summary, detail_count: Array.isArray(details) ? details.length : 0 };
}

function previewAppendix(appendix: unknown) {
  const full = appendix as { lines: Record<string, unknown>[] };
  return {
    ...full,
    lines: full.lines.map((line) => ({
      ...line,
      source_anchor: previewAnchor(line.source_anchor as Record<string, unknown>),
      ledger_anchor: previewAnchor(line.ledger_anchor as Record<string, unknown>),
    })),
  };
}

function packagePreview(readinessPayload = readiness, policyPayload = frameworkPolicy, traceabilityPayload: unknown = traceabilityAppendix) {
  const {
    snapshot_id: _snapshotId,
    package_decision_id: _decisionId,
    frozen_at: _frozenAt,
    input_manifest: _manifest,
    ...preview
  } = packageDocument(readinessPayload, policyPayload, traceabilityPayload);
  return { ...preview, status: "draft", sections: { ...preview.sections, traceability_appendix: previewAppendix(traceabilityPayload) } };
}

// The evidence pages of the preview: slices of the complete fixture lists.
function evidencePage(path: string, traceabilityPayload: unknown) {
  const url = new URL(path, "http://localhost");
  const limit = Number(url.searchParams.get("limit"));
  const offset = Number(url.searchParams.get("offset"));
  if (url.pathname === "/api/reports/package/manifest-entries") {
    const entries = packageDocument().input_manifest;
    return { total: entries.length, limit, offset, entries: entries.slice(offset, offset + limit) };
  }
  const lineId = url.searchParams.get("line_id");
  const anchor = url.searchParams.get("anchor") as "source_anchor" | "ledger_anchor";
  type FixtureLine = { line_id: string; source_anchor: { details?: unknown[] }; ledger_anchor: { details?: unknown[] } };
  const line = (traceabilityPayload as { lines: FixtureLine[] }).lines.find((item) => item.line_id === lineId);
  const details = line?.[anchor]?.details ?? [];
  return { line_id: lineId, anchor, total: details.length, limit, offset, details: details.slice(offset, offset + limit) };
}

const evidenceRequests = (prefix: "/api/reports/package/line-details?" | "/api/reports/package/manifest-entries?") =>
  mockedApiFetch.mock.calls.map(([path]) => String(path)).filter((path) => path.startsWith(prefix));

const packageSnapshot = {
  id: "snap-001",
  package_id: "personal-financial-report-package",
  status: "trusted",
  framework_id: "personal_us_gaap_like",
  start_date: "2025-05-20",
  end_date: "2026-05-20",
  as_of_date: "2026-05-20",
  currency: "SGD",
  readiness_state: "ready",
  is_latest: true,
  created_at: "2026-05-20T12:00:00Z",
  document: packageDocument({ ...readiness, state: "ready", label: "Ready", blocking_count: 0, blockers: [] }, frameworkPolicy, traceabilityAppendix, "frozen", "snap-001"),
};
const packageSnapshotJsonDownloadName = "Download JSON snapshot snap-001 for US-like 2025-05-20 to 2026-05-20";
const packageSnapshotCsvDownloadName = "Download CSV snapshot snap-001 for US-like 2025-05-20 to 2026-05-20";

const lineageResponse = {
  anchor: { id: "node-ledger-line", node_kind: "ledger_line", entity_type: "journal_line", entity_id: journalLineId, properties: { amount: "120.00", currency: "SGD" } },
  nodes: [
    { id: "node-uploaded-document", node_kind: "source_document", entity_type: "uploaded_document", entity_id: uploadedDocumentId, properties: { original_filename: "may-statement.csv" } },
    { id: "node-extracted-record", node_kind: "extracted_record", entity_type: "bank_statement_transaction", entity_id: statementTxnId, properties: { description: "Salary" } },
    { id: "node-atomic-fact", node_kind: "atomic_fact", entity_type: "atomic_transaction", entity_id: atomicTransactionId, properties: { amount: "120.00" } },
    { id: "node-ledger-entry", node_kind: "ledger_entry", entity_type: "journal_entry", entity_id: journalEntryId, properties: { status: "posted" } },
    { id: "node-ledger-line", node_kind: "ledger_line", entity_type: "journal_line", entity_id: journalLineId, properties: { amount: "120.00" } },
    { id: "node-report-line", node_kind: "report_line", entity_type: "package_traceability_line", entity_id: reportLineNodeId, properties: { line_id: "balance_sheet.total_assets" } },
  ],
  edges: [
    { id: "edge-parsed", relation: "parsed_into", direction: "upstream", depth: 4, from_node_id: "node-uploaded-document", to_node_id: "node-extracted-record", properties: {} },
    { id: "edge-deduped", relation: "deduped_into", direction: "upstream", depth: 3, from_node_id: "node-extracted-record", to_node_id: "node-atomic-fact", properties: {} },
    { id: "edge-posted", relation: "posted_as", direction: "upstream", depth: 2, from_node_id: "node-atomic-fact", to_node_id: "node-ledger-entry", properties: {} },
    { id: "edge-contains", relation: "contains", direction: "upstream", depth: 1, from_node_id: "node-ledger-entry", to_node_id: "node-ledger-line", properties: {} },
    { id: "edge-report", relation: "aggregated_into", direction: "downstream", depth: 1, from_node_id: "node-ledger-line", to_node_id: "node-report-line", properties: {} },
  ],
  blockers: [],
  max_depth: 6,
};

function mockPackageApi(
  readinessPayload = readiness,
  policyPayload = frameworkPolicy,
  traceabilityPayload: unknown = traceabilityAppendix,
  lineagePayload: unknown = lineageResponse,
  snapshotPayloads: unknown[] = [packageSnapshot],
  snapshotGenerateResult: unknown = packageSnapshot,
) {
  mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
    if (path === "/api/reports/package/snapshots") return Promise.resolve(snapshotPayloads);
    if (path === "/api/reports/package/snapshots/snap-001") return Promise.resolve(snapshotGenerateResult);
    if (path === "/api/reports/package/generate" && options?.method === "POST") {
      return snapshotGenerateResult instanceof Error ? Promise.reject(snapshotGenerateResult) : Promise.resolve(snapshotGenerateResult);
    }
    if (path.startsWith("/api/reports/package?")) return Promise.resolve(packagePreview(readinessPayload, policyPayload, traceabilityPayload));
    if (path.startsWith("/api/reports/package/line-details?") || path.startsWith("/api/reports/package/manifest-entries?")) {
      return Promise.resolve(evidencePage(path, traceabilityPayload));
    }
    if (path.startsWith("/api/evidence/lineage?")) {
      return lineagePayload instanceof Error ? Promise.reject(lineagePayload) : Promise.resolve(lineagePayload);
    }
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

function expectPinnedPackageDates(path: string) {
  const params = new URL(path, "http://localhost").searchParams;
  expect(params.get("start_date")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  expect(params.get("end_date")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  expect(params.get("as_of_date")).toBe(params.get("end_date"));
}

function expectPackageDates(path: string, reportDate: string, startDate: string) {
  const params = new URL(path, "http://localhost").searchParams;
  expect(params.get("start_date")).toBe(startDate);
  expect(params.get("end_date")).toBe(reportDate);
  expect(params.get("as_of_date")).toBe(reportDate);
}

function expectInsideClosedAuditDetails(text: string | RegExp) {
  const details = screen
    .getAllByText(text)
    .map((node) => node.closest("details"))
    .find((candidate): candidate is HTMLDetailsElement => candidate instanceof HTMLDetailsElement && Boolean(within(candidate).queryByText(/audit details/i)));
  if (!details) throw new Error(`Expected ${String(text)} inside closed audit details.`);
  expect(details).not.toHaveAttribute("open");
  expect(within(details).getByText(/audit details/i)).toBeInTheDocument();
  return details;
}

describe("PersonalReportPackagePage", () => {
  beforeEach(() => {
    setTestUrl("/reports?tab=package");
  });

  afterEach(() => {
    mockedApiDownload.mockReset();
    mockedApiFetch.mockReset();
    vi.mocked(track).mockReset();
  });

  it("AC-reporting.package-document.12 previews and generates the selected month through the page", async () => {
    mockPackageApi();
    // March 2025 in SGD, set by the dimension bar (1M, end 2025-03-31).
    setTestUrl("/reports?tab=package&period=1M&end=2025-03-31&currency=SGD");
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("button", { name: /Generate Snapshot/i });
    const preview = mockedApiFetch.mock.calls.map(([path]) => String(path)).find((p) => p.includes("framework_id=personal_us_gaap_like") && p.includes("start_date=2025-03-01"));
    expect(preview).toBeDefined();
    expectPackageDates(preview!, "2025-03-31", "2025-03-01");
    fireEvent.click(screen.getByRole("button", { name: /Generate Snapshot/i }));
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/reports/package/generate",
        expect.objectContaining({
          method: "POST",
          // No include_restricted: the backend reads PACKAGE_INCLUDE_RESTRICTED (#2645).
          body: JSON.stringify({ framework_id: "personal_us_gaap_like", start_date: "2025-03-01", end_date: "2025-03-31", as_of_date: "2025-03-31", currency: "SGD" }),
        }),
      ),
    );
  });

  it("AC-reporting.package-document.12 replaces an invalid period in the URL with the current period and never requests it", async () => {
    mockPackageApi();
    setTestUrl("/reports?tab=package&period=1M&end=2025-02-30");
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("button", { name: /Generate Snapshot/i });
    const current = readReportFilters(new URLSearchParams("period=1M"));
    const previews = mockedApiFetch.mock.calls.map(([path]) => String(path)).filter((p) => p.startsWith("/api/reports/package?"));
    expect(previews.length).toBeGreaterThan(0);
    previews.forEach((p) => expectPackageDates(p, current.endDate, current.startDate));
    expect(previews.some((p) => p.includes("2025-02-30"))).toBe(false);
    expect(screen.queryByLabelText("Package report date")).toBeNull();
  });

  it("AC-reporting.package-document.12 refreshes preview when only the start changes and reopens the saved monthly period", async () => {
    const monthly = {
      ...packageSnapshot,
      start_date: "2025-03-01",
      end_date: "2025-03-31",
      as_of_date: "2025-04-01",
      document: { ...packageSnapshot.document, context: { ...packageSnapshot.document.context, start_date: "2025-03-01", end_date: "2025-03-31", as_of_date: "2025-04-01" } },
    };
    mockPackageApi(readiness, frameworkPolicy, traceabilityAppendix, lineageResponse, [monthly], monthly);
    setTestUrl("/reports?tab=package&start=2025-03-01&end=2025-03-31");
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("button", { name: /Generate Snapshot/i });
    mockedApiFetch.mockClear();
    // The custom period of the dimension bar: only the start changes.
    fireEvent.change(screen.getByLabelText("Period start"), { target: { value: "2025-03-02" } });
    await waitFor(() => expect(mockedApiFetch.mock.calls.some(([path]) => String(path).includes("start_date=2025-03-02"))).toBe(true));
    await screen.findByRole("button", { name: /Generate Snapshot/i });
    expectPackageDates(String(mockedApiFetch.mock.calls.find(([path]) => String(path).startsWith("/api/reports/package?"))![0]), "2025-03-31", "2025-03-02");
    mockedApiFetch.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Reopen" }));
    await screen.findByText("Frozen snapshot snap-001");
    const cover = within(screen.getByRole("region", { name: "Report package cover" }));
    expect(cover.getByText("2025-03-01 to 2025-03-31")).toBeInTheDocument();
    expect(cover.getByText("2025-04-01")).toBeInTheDocument();
    expect(cover.getByText("Balances as of").nextElementSibling).toHaveTextContent("2025-04-01");
    expect(mockedApiFetch.mock.calls.some(([path]) => String(path).includes("/package?"))).toBe(false);

    // A new period in the dimension bar closes the snapshot and previews the new period.
    act(() => setTestUrl("/reports?tab=package&start=2025-04-01&end=2025-04-30"));
    await waitFor(() => expect(screen.queryByText("Frozen snapshot snap-001")).toBeNull());
    await waitFor(() => expect(mockedApiFetch.mock.calls.some(([path]) => String(path).includes("start_date=2025-04-01"))).toBe(true));
  });

  // AC-reporting.net-worth-scope.23
  it("#2645 labels the package net worth from the scope that the document context records", async () => {
    mockPackageApi();
    const base = mockedApiFetch.getMockImplementation()!;
    mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("/api/reports/package?")) {
        const preview = packagePreview();
        return Promise.resolve({ ...preview, context: { ...preview.context, include_restricted: false } });
      }
      return base(path, options);
    });
    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));

    const balance = await screen.findByRole("heading", { name: "Balance Sheet", level: 2 });
    expect(within(balance.closest("section")!).getByText("Liquid net worth")).toBeInTheDocument();
    expect(screen.queryByText("This snapshot does not record its restricted-holdings scope, so no net worth is shown.")).toBeNull();
  });

  it("AC8.13.92 surfaces package API failures as a visible loading error", async () => {
    mockedApiFetch.mockRejectedValue(new Error("package document unavailable"));
    renderPackagePage();
    expect(screen.getByText("Loading package document...")).toBeInTheDocument();
    expect(await screen.findByText("package document unavailable")).toBeInTheDocument();
  });

  // AC-reporting.fe-ia-reports.16
  it("AC20.6.1 AC22.8.3 AC22.13.3 requires explicit framework selection before loading framework-scoped package output", async () => {
    mockPackageApi();
    renderPackagePage();
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("/api/reports/package?"), expect.objectContaining({ signal: expect.any(Object) })));
    expect(await screen.findByRole("button", { name: "US-like" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "HK-like" })).toBeInTheDocument();
    expect(screen.getByText("Select a framework before package output is loaded.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Package setup guidance" })).toBeInTheDocument();
    const setupToc = screen.getByRole("navigation", { name: "Report package table of contents" });
    expect(within(setupToc).getByRole("link", { name: "Reporting Framework" })).toHaveAttribute("href", "#package-framework-selection");
    expect(within(setupToc).getByRole("link", { name: "Balance Sheet ready" })).toHaveAttribute("href", "#package-section-balance_sheet");
    expect(mockedApiFetch.mock.calls.some(([path]) => String(path).includes("framework_id="))).toBe(false);
    expect(screen.queryByText("Report Readiness")).not.toBeInTheDocument();
  });

  it("AC20.6.1 renders the API error when the initial package document cannot load", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/reports/package?")) return Promise.reject(new Error("Document unavailable"));
      if (path === "/api/reports/package/snapshots") return Promise.resolve([]);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
    renderPackagePage();
    expect(await screen.findByText("Document unavailable")).toBeInTheDocument();
  });

  it("AC20.6.1 ignores the initial package document response after unmount", async () => {
    let resolveDocument!: (value: ReturnType<typeof packagePreview>) => void;
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/reports/package?")) return new Promise((resolve) => { resolveDocument = resolve; });
      if (path === "/api/reports/package/snapshots") return Promise.resolve([]);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
    const { unmount } = renderPackagePage();
    expect(screen.getByText("Loading package document...")).toBeInTheDocument();
    unmount();
    await act(async () => { resolveDocument(packagePreview()); });
  });

  it("AC20.6.1 renders the API error when selected framework package output cannot load", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/reports/package?") && !path.includes("framework_id=")) return Promise.resolve(packagePreview());
      if (path === "/api/reports/package/snapshots") return Promise.resolve([]);
      if (path.startsWith("/api/reports/package?framework_id=")) return Promise.reject(new Error("Framework package unavailable"));
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    expect(await screen.findByText("Framework package unavailable")).toBeInTheDocument();
  });

  it("AC20.6.1 keeps canceled framework package requests from surfacing errors", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/reports/package?") && !path.includes("framework_id=")) return Promise.resolve(packagePreview());
      if (path === "/api/reports/package/snapshots") return Promise.resolve([]);
      if (path.startsWith("/api/reports/package?framework_id=")) return Promise.reject(new DOMException("Canceled", "AbortError"));
      return new Promise(() => undefined);
    });
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await waitFor(() => expect(screen.queryByText("Failed to load package data.")).not.toBeInTheDocument());
    expect(screen.getByRole("status", { name: "Loading report package" })).toHaveAttribute("aria-busy", "true");
  });

  it("EPIC-022 #867 offers a print / save-as-PDF export of the loaded package", async () => {
    mockPackageApi();
    const printMock = vi.fn();
    const originalPrint = window.print;
    window.print = printMock;
    try {
      renderPackagePage();
      fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
      fireEvent.click(await screen.findByRole("button", { name: /Print \/ Save as PDF/i }));
      expect(printMock).toHaveBeenCalled();
    } finally {
      window.print = originalPrint;
    }
  });

  it("AC20.6.1 AC20.7.1 loads one typed document with the selected framework", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("/api/reports/package?framework_id=personal_us_gaap_like"), expect.objectContaining({ signal: expect.any(Object) })));
    const documentCall = mockedApiFetch.mock.calls.find(([path]) => String(path).startsWith("/api/reports/package?framework_id=personal_us_gaap_like"));
    expect(documentCall).toBeTruthy();
    expectPinnedPackageDates(String(documentCall![0]));
    for (const retiredPath of ["/readiness", "/framework-policy", "/annualized-income-schedule", "/traceability"]) {
      expect(mockedApiFetch.mock.calls.some(([path]) => String(path).includes(retiredPath))).toBe(false);
    }
    expect(await screen.findByRole("heading", { name: "Reporting Basis" })).toBeInTheDocument();
    expect(screen.getAllByText("US-like").length).toBeGreaterThanOrEqual(1);
    expectInsideClosedAuditDetails("policy-result:personal_us_gaap_like:2025-05-20:2026-05-20:fixture");
    expectInsideClosedAuditDetails("assets.marketable_securities");
    expectInsideClosedAuditDetails("unsupported_policy_domain");
  });

  it("AC20.6.1 keeps framework package sections pinned to the selected report date", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Reporting Basis" });
    act(() => setTestUrl("/reports?tab=package&end=2026-04-30"));
    await waitFor(() => expect(mockedApiFetch.mock.calls.some(([path]) => String(path).includes("end_date=2026-04-30"))).toBe(true));
    const selectedDateCalls = mockedApiFetch.mock.calls.map(([path]) => String(path)).filter((p) => p.includes("end_date=2026-04-30"));
    expect(selectedDateCalls).toHaveLength(1);
    expect(selectedDateCalls[0]).toContain("/api/reports/package?framework_id=personal_us_gaap_like");
    selectedDateCalls.forEach((p) => expectPackageDates(p, "2026-04-30", "2025-05-01"));
  });

  it("AC20.6.1 uses the dimension-bar period across leap years", async () => {
    mockPackageApi();
    setTestUrl("/reports?tab=package&period=1M&end=2024-02-29");
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Reporting Basis" });
    const datedCalls = (end: string) => mockedApiFetch.mock.calls.map(([path]) => String(path)).filter((p) => p.includes(`end_date=${end}`));
    expect(datedCalls("2024-02-29").length).toBeGreaterThan(0);
    datedCalls("2024-02-29").forEach((p) => expectPackageDates(p, "2024-02-29", "2024-02-01"));
    fireEvent.click(screen.getByRole("button", { name: "Previous period" }));
    await waitFor(() => expect(datedCalls("2024-01-31").length).toBeGreaterThan(0));
    datedCalls("2024-01-31").forEach((p) => expectPackageDates(p, "2024-01-31", "2024-01-01"));
    fireEvent.click(screen.getByRole("button", { name: "Next period" }));
    fireEvent.click(screen.getByRole("button", { name: "Next period" }));
    await waitFor(() => expect(datedCalls("2024-03-31").length).toBeGreaterThan(0));
    datedCalls("2024-03-31").forEach((p) => expectPackageDates(p, "2024-03-31", "2024-03-01"));
  });

  // AC-reporting.fe-viz-reports.11
  it("AC5.17.2 downloads package CSV through authenticated apiDownload", async () => {
    const createObjectUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:package-csv");
    const revokeObjectUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    mockedApiDownload.mockResolvedValue({ blob: new Blob(["package_id,section_id"], { type: "text/csv" }), filename: "personal-report-package.csv" });
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    fireEvent.click(await screen.findByRole("button", { name: packageSnapshotCsvDownloadName }));
    await waitFor(() => expect(mockedApiDownload).toHaveBeenCalledWith("/api/reports/package/snapshots/snap-001/export?format=csv"));
    createObjectUrl.mockRestore();
    revokeObjectUrl.mockRestore();
  });

  // AC-reporting.fe-viz-reports.12
  it("AC5.19.4 generates and downloads package snapshots", async () => {
    const createObjectUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:package-snapshot");
    const revokeObjectUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    mockedApiDownload.mockResolvedValue({ blob: new Blob(["package snapshot"], { type: "text/csv" }), filename: "personal-report-package-snap-001.csv" });
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    fireEvent.click(await screen.findByRole("button", { name: /Generate Snapshot/i }));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/reports/package/generate", expect.objectContaining({ method: "POST", body: expect.stringContaining('"framework_id":"personal_us_gaap_like"') })));
    await screen.findByText("Frozen snapshot snap-001");
    expect(await screen.findByRole("heading", { name: "Recent Snapshots" })).toBeInTheDocument();
    expect(screen.getAllByText("Trusted").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: packageSnapshotJsonDownloadName }));
    await waitFor(() => expect(mockedApiDownload).toHaveBeenCalledWith("/api/reports/package/snapshots/snap-001/export?format=json"));
    fireEvent.click(screen.getByRole("button", { name: packageSnapshotCsvDownloadName }));
    await waitFor(() => expect(mockedApiDownload).toHaveBeenCalledWith("/api/reports/package/snapshots/snap-001/export?format=csv"));
    createObjectUrl.mockRestore();
    revokeObjectUrl.mockRestore();
  });

  it("AC-reporting.package-document.3 renders a populated document and reopens the selected frozen snapshot", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    expect(await screen.findByText("SGD 100,000")).toBeInTheDocument();
    expect(screen.getAllByText("SGD 137,400").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("SGD 22,500")).toBeInTheDocument();
    expect(screen.getByText("ACME")).toBeInTheDocument();
    expectInsideClosedAuditDetails("2 details");
    expect(screen.getByText("Live preview. Generate a snapshot to freeze these exact inputs and totals.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reopen" }));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/reports/package/snapshots/snap-001", expect.objectContaining({ signal: expect.any(Object) })));
    expect(await screen.findByText("Frozen snapshot snap-001")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
    // A frozen snapshot stores every detail and manifest entry: the page reads them without a request.
    fireEvent.click(screen.getByRole("button", { name: "Show evidence details for Total Assets" }));
    expect(await screen.findByText(`statement_transaction:${statementTxnId}`)).toBeInTheDocument();
    expect(screen.getByText(`journal_line:${journalLineId}`)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Authority manifest audit details"));
    expect(await screen.findByText(/77777777-7777-4777-8777-777777777777 journal_command/)).toBeInTheDocument();
    expect(evidenceRequests("/api/reports/package/line-details?")).toEqual([]);
    expect(evidenceRequests("/api/reports/package/manifest-entries?")).toEqual([]);
  });

  it("renders absent disclosure list values explicitly", () => {
    expect(renderCsv()).toBe("none");
    expect(renderSourceClasses([])).toBe("none");
  });

  it("AC22.18.3 tracks REPORT_GENERATED with the framework id after a successful snapshot", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    fireEvent.click(await screen.findByRole("button", { name: /Generate Snapshot/i }));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/reports/package/generate", expect.objectContaining({ method: "POST" })));
    await waitFor(() => expect(vi.mocked(track)).toHaveBeenCalledWith(ANALYTICS_EVENTS.REPORT_GENERATED, expect.objectContaining({ framework_id: "personal_us_gaap_like" })));
  });

  it("AC22.18.3 does not track REPORT_GENERATED when snapshot generation fails", async () => {
    mockPackageApi(readiness, frameworkPolicy, traceabilityAppendix, lineageResponse, [packageSnapshot], new Error("Snapshot generation failed"));
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    fireEvent.click(await screen.findByRole("button", { name: /Generate Snapshot/i }));
    expect(await screen.findByText("Snapshot generation failed")).toBeInTheDocument();
    expect(vi.mocked(track)).not.toHaveBeenCalledWith(ANALYTICS_EVENTS.REPORT_GENERATED, expect.anything());
  });

  it("AC5.19.4 surfaces package snapshot generation failures", async () => {
    mockPackageApi(readiness, frameworkPolicy, traceabilityAppendix, lineageResponse, [packageSnapshot], new Error("Snapshot generation failed"));
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    fireEvent.click(await screen.findByRole("button", { name: /Generate Snapshot/i }));
    expect(await screen.findByText("Snapshot generation failed")).toBeInTheDocument();
  });

  it("AC5.19.4 surfaces package snapshot download failures", async () => {
    mockedApiDownload.mockRejectedValue(new Error("Snapshot download failed"));
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    fireEvent.click(await screen.findByRole("button", { name: packageSnapshotCsvDownloadName }));
    expect(await screen.findByText("Snapshot download failed")).toBeInTheDocument();
  });

  it("AC5.19.4 renders snapshot timestamps with missing and invalid fallbacks", async () => {
    mockPackageApi(readiness, frameworkPolicy, traceabilityAppendix, lineageResponse, [
      { ...packageSnapshot, id: "snap-missing-created-at", created_at: null },
      { ...packageSnapshot, id: "snap-invalid-created-at", created_at: "bad-date" },
    ]);
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    expect(await screen.findByText("Not recorded")).toBeInTheDocument();
    expect(screen.getByText("bad-date")).toBeInTheDocument();
  });

  it("AC20.6.1 loads HK-like package output and renders empty evidence bundle metadata", async () => {
    mockPackageApi(readiness, { ...frameworkPolicy, result_id: "policy-result:personal_hkfrs_like:2025-05-20:2026-05-20:fixture", framework_id: "personal_hkfrs_like", decisions: [], gaps: [] });
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "HK-like" }));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("/api/reports/package?framework_id=personal_hkfrs_like"), expect.objectContaining({ signal: expect.any(Object) })));
    expect(await screen.findByRole("heading", { name: "Reporting Basis" })).toBeInTheDocument();
    expect(await screen.findByText("HK-like selected for this package.")).toBeInTheDocument();
    expect(screen.getAllByText("HK-like").length).toBeGreaterThan(0);
    expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(2);
    expectInsideClosedAuditDetails("personal_hkfrs_like");
    expectInsideClosedAuditDetails("none");
  });

  it("AC20.6.1 ignores stale framework package responses when selection changes", async () => {
    const usSignals: AbortSignal[] = [];
    const resolveUsRequests: Array<() => void> = [];
    const hkPolicy = { ...frameworkPolicy, result_id: "policy-result:personal_hkfrs_like:2025-05-20:2026-05-20:fixture", framework_id: "personal_hkfrs_like", decisions: [], gaps: [] };

    mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("/api/reports/package?") && !path.includes("framework_id=")) return Promise.resolve(packagePreview());
      if (path === "/api/reports/package/snapshots") return Promise.resolve([packageSnapshot]);
      if (path.startsWith("/api/reports/package?framework_id=personal_us_gaap_like")) {
        if (options?.signal) usSignals.push(options.signal);
        return new Promise((resolve) => { resolveUsRequests.push(() => resolve(packagePreview(readiness, frameworkPolicy, traceabilityAppendix))); });
      }
      if (path.startsWith("/api/reports/package?framework_id=personal_hkfrs_like")) return Promise.resolve(packagePreview(readiness, hkPolicy, traceabilityAppendix));
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await waitFor(() => expect(usSignals.length).toBeGreaterThan(0));
    fireEvent.click(await screen.findByRole("button", { name: "HK-like" }));
    await waitFor(() => expect(usSignals.every((signal) => signal.aborted)).toBe(true));
    expect((await screen.findAllByText("policy-result:personal_hkfrs_like:2025-05-20:2026-05-20:fixture")).length).toBeGreaterThanOrEqual(1);
    expectInsideClosedAuditDetails("policy-result:personal_hkfrs_like:2025-05-20:2026-05-20:fixture");
    expect(screen.queryByText("policy-result:personal_us_gaap_like:2025-05-20:2026-05-20:fixture")).not.toBeInTheDocument();
    await act(async () => { resolveUsRequests.forEach((resolve) => resolve()); });
    expect(screen.queryByText("policy-result:personal_us_gaap_like:2025-05-20:2026-05-20:fixture")).not.toBeInTheDocument();
  });

  // AC-reporting.fe-viz-reports.3
  it("AC5.9.3 renders personal package contract sections from API", async () => {
    mockPackageApi();
    renderPackagePage();
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("/api/reports/package?"), expect.objectContaining({ signal: expect.any(Object) })));
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Balance Sheet" });
    expect(screen.getAllByText("Personal Report Package").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("personal-financial-report-package").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("balance_sheet").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("heading", { name: "Balance Sheet" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Annualized Income Schedule" })).toBeInTheDocument();
  });

  // AC-reporting.fe-ia-reports.14
  it("AC22.8.1 titles package sections with human labels, not developer snake_case identifiers", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Authority Coverage" });
    for (const heading of ["Report Readiness", "Authority Coverage", "Reporting Basis", "Traceability Summary"]) {
      expect(screen.getAllByText(heading).length).toBeGreaterThanOrEqual(1);
    }
    for (const raw of ["framework_selection", "report_readiness", "source_trust_summary", "framework_policy_result"]) {
      expect(screen.queryByText(raw)).toBeNull();
    }
  });

  // AC-reporting.fe-ia-reports.15
  it("AC22.8.2 AC22.13.3 renders a readable package cover and linked table of contents", async () => {
    mockPackageApi();
    setTestUrl("/reports?tab=package&end=2026-05-20");
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("button", { name: /Generate Snapshot/i });
    const cover = await screen.findByRole("region", { name: "Report package cover" });
    expect(within(cover).getByText("Personal Report Package")).toBeInTheDocument();
    expect(within(cover).getByText("personal-financial-report-package")).toBeInTheDocument();
    expect(within(cover).getByText("US-like")).toBeInTheDocument();
    expect(within(cover).getByText("2026-05-20")).toBeInTheDocument();
    const toc = screen.getByRole("navigation", { name: "Report package table of contents" });
    for (const [label, href] of [
      ["Report Readiness", "#package-readiness"],
      ["Authority Coverage", "#package-input-manifest"],
      ["Reporting Basis", "#package-framework-policy"],
      ["Balance Sheet ready", "#package-section-balance_sheet"],
      ["Traceability Summary", "#package-traceability-detail"],
    ] as const) {
      expect(within(toc).getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
  });

  it("AC22.8.3 reserves the framework-package layout while package sections load", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/reports/package?") && !path.includes("framework_id=")) return Promise.resolve(packagePreview());
      if (path === "/api/reports/package/snapshots") return Promise.resolve([]);
      return new Promise(() => undefined);
    });
    const { container } = renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    expect(screen.getByRole("status", { name: "Loading report package" })).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("navigation", { name: "Report package table of contents" })).toBeInTheDocument();
    expect(container.querySelectorAll("[data-testid='skeleton-block']").length).toBeGreaterThanOrEqual(10);
    expect(screen.queryByText("Loading framework package...")).not.toBeInTheDocument();
  });

  // AC-reporting.fe-remainder-reports.11
  it("AC19.5.4 renders package readiness before report package output", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("/api/reports/package?framework_id=personal_us_gaap_like"), expect.objectContaining({ signal: expect.any(Object) })));
    const readinessHeading = await screen.findByRole("heading", { name: "Report Readiness" });
    const balanceSheetHeading = screen.getByRole("heading", { name: "Balance Sheet" });
    expect(readinessHeading.compareDocumentPosition(balanceSheetHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("2 blockers must be resolved before package output is trusted.")).toBeInTheDocument();
    expect(screen.getByText("Pending source review")).toBeInTheDocument();
    expectInsideClosedAuditDetails("pending_review");
    expect(screen.getByText("Balance validation mismatch")).toBeInTheDocument();
    expect(screen.getByText("Opening and closing balances must validate before report totals are trusted.")).toBeInTheDocument();
    expect(screen.getByText("Authority Decisions")).toBeInTheDocument();
    expect(screen.getByText("Authoritative Inputs")).toBeInTheDocument();
    expect(screen.getByText("Unproven Inputs")).toBeInTheDocument();
  });

  // AC-reporting.fe-remainder-reports.12
  it("AC19.5.5 renders non-blocked readiness states without blocker cards", async () => {
    mockPackageApi({ ...readiness, state: "generated", label: "Generated", blocking_count: 0, blockers: [] });
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await waitFor(() => expect(screen.getByText("Current package state is generated.")).toBeInTheDocument());
    expect(screen.queryByText("Pending source review")).not.toBeInTheDocument();
  });

  // AC-reporting.fe-remainder-reports.14
  it("AC19.9.2 renders decision authority coverage before traceability details", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    const authorityCoverage = await screen.findByRole("heading", { name: "Authority Coverage" });
    const traceability = await screen.findByRole("heading", { name: "Traceability Summary" });
    expect(authorityCoverage.compareDocumentPosition(traceability) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("Trust comes from the current decision graph pinned into this document, not a source label.")).toBeInTheDocument();
    expect(screen.getByText("1 decisions")).toBeInTheDocument();
    // The preview has no manifest entries. They load when the audit details open (#2583 S8).
    expect(screen.queryByText(/77777777-7777-4777-8777-777777777777/)).not.toBeInTheDocument();
    expect(evidenceRequests("/api/reports/package/manifest-entries?")).toEqual([]);
    fireEvent.click(screen.getByText("Authority manifest audit details"));
    expect(
      await screen.findByText(new RegExp(`77777777-7777-4777-8777-777777777777 journal_command:statement-transaction:${statementTxnId}@fixture-v1`)),
    ).toBeInTheDocument();
    expect(evidenceRequests("/api/reports/package/manifest-entries?")).toEqual([expect.stringContaining("limit=200&offset=0")]);
  });

  // AC-reporting.fe-ia-reports.23
  it("AC22.19.1 renders the loaded package with reader-first labels before proof internals", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    expect(await screen.findByRole("heading", { name: "Authority Coverage" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Authority Coverage" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Reporting Basis" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Traceability Summary" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Framework Policy" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Source Trust" })).not.toBeInTheDocument();
    expect(screen.getByText("Trust comes from the current decision graph pinned into this document, not a source label.")).toBeInTheDocument();
    expect(screen.getByText("Report lines with evidence")).toBeInTheDocument();
    expect(screen.getByText("Reporting gaps")).toBeInTheDocument();
    expect(screen.queryByText(/77777777-7777-4777-8777-777777777777/)).not.toBeInTheDocument();
    expectInsideClosedAuditDetails("Framework Policy Result");
    expectInsideClosedAuditDetails("unsupported_policy_domain");
    expectInsideClosedAuditDetails("pending_review");
  });

  it("AC22.19.1 humanizes review states in the reader-first package layer", async () => {
    mockPackageApi(
      readiness,
      { ...frameworkPolicy, decisions: [{ ...frameworkPolicy.decisions[0], domain: "manual_private_asset", classification: "Private asset.", presentation: "Private asset presentation.", review_state: "pending_review" }] },
      { ...traceabilityAppendix, status: "pending_review" },
    );
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    const policyArticle = (await screen.findByText("Manual Private Asset")).closest("article");
    if (!(policyArticle instanceof HTMLElement)) throw new Error("Expected framework policy decision article.");
    expect(within(policyArticle).getByText("Pending Review")).toBeInTheDocument();
    expect(within(policyArticle).queryByText("pending_review")).not.toBeInTheDocument();
    const traceabilitySection = screen.getByRole("heading", { name: "Traceability Summary" }).closest("section");
    if (!(traceabilitySection instanceof HTMLElement)) throw new Error("Expected traceability section.");
    expect(within(traceabilitySection).getAllByText("Pending Review").length).toBeGreaterThanOrEqual(1);
    expect(within(traceabilitySection).queryByText("pending_review")).not.toBeInTheDocument();
  });

  // AC-reporting.fe-ia-reports.24
  it("AC22.19.2 keeps proof and policy internals in keyboard-reachable audit details", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Reporting Basis" });
    for (const summary of ["Readiness audit details", "Authority manifest audit details", "Reporting basis audit details", "Traceability audit details", "Export audit details"]) {
      const details = screen.getByText(summary).closest("details");
      expect(details).not.toBeNull();
      expect(details).not.toHaveAttribute("open");
      fireEvent.click(screen.getByText(summary));
      expect(details).toHaveAttribute("open");
    }
    expect(screen.getByText("Matrix Version")).toBeInTheDocument();
    expect(screen.getByText("balance_sheet.total_assets")).toBeInTheDocument();
    expect(await screen.findByText(/77777777-7777-4777-8777-777777777777/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`journal_command:statement-transaction:${statementTxnId}@fixture-v1`))).toBeInTheDocument();
    expect(screen.getByText("static_contract_note")).toBeInTheDocument();
  });

  // AC-reporting.fe-ia-reports.25
  it("AC22.19.3 keeps export proof metadata behind a print-hidden export audit disclosure", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Export Options" });
    expect(screen.queryByRole("heading", { name: "Export Contract" })).not.toBeInTheDocument();
    expect(screen.getByText("Snapshot exports are built from the selected reporting basis and evidence references.")).toBeInTheDocument();
    const exportAudit = screen.getByText("Export audit details").closest("details");
    expect(exportAudit).toHaveClass("print:hidden");
    expectInsideClosedAuditDetails("Framework Policy Matrix Version");
    expectInsideClosedAuditDetails(/atomic_position:private-token/);
  });

  // AC-reporting.fe-viz-reports.4
  it("AC5.9.4 renders export contract metadata", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Export Options" });
    expect(screen.getByText("json, csv")).toBeInTheDocument();
    expectInsideClosedAuditDetails("package_id, section_id, line_id, label, amount, currency, source_state, selected_framework_id, framework_policy_result_id, framework_policy_matrix_version, evidence_bundle_references");
    expectInsideClosedAuditDetails("Framework Policy Result");
    expect(screen.getAllByText("1.0").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("string")).toBeInTheDocument();
    expect(screen.getAllByText(/atomic_position:private-token/).length).toBeGreaterThanOrEqual(1);
  });

  // AC-reporting.fe-viz-reports.5 / AC-reporting.fe-viz-reports.1
  // AC-portfolio.fe-assets2.7 / AC-portfolio.fe-assets2.8 / AC-portfolio.fe-assets2.10
  it("AC5.11.2 renders annualized income schedule values and restricted treatment", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await waitFor(() => expect(screen.getByText("Annualized Income Schedule")).toBeInTheDocument());
    expect(screen.getAllByText("SGD 137,400").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Salary")).toBeInTheDocument();
    expect(screen.getByText("SGD 120,000")).toBeInTheDocument();
    expect(screen.getByText("Bonus")).toBeInTheDocument();
    expect(screen.getByText("SGD 15,000")).toBeInTheDocument();
    expect(screen.getByText("Dividend")).toBeInTheDocument();
    expect(screen.getAllByText("SGD 2,400").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("SHOP-RSU")).toBeInTheDocument();
    expect(screen.getByText("SGD 12,500")).toBeInTheDocument();
    expect(screen.getByText("exclude_restricted_holdings")).toBeInTheDocument();
    expect(screen.getByText("Personal management report only; not tax advice.")).toBeInTheDocument();
    // The figures come from the package document: no separate annualized-income request.
    expect(mockedApiFetch.mock.calls.some(([path]) => String(path).startsWith("/api/income/annualized"))).toBe(false);
  });

  // AC-reporting.fe-viz-reports.6
  it("AC5.12.3 renders package notes and disclosure basis", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByText("Basis of Preparation");
    expect(screen.getAllByText("Notes & Disclosures").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Basis of Preparation")).toBeInTheDocument();
    expect(screen.getByText("Valuation Basis")).toBeInTheDocument();
    expect(screen.getByText("manual_valuation_snapshots")).toBeInTheDocument();
    expect(screen.getByText("This personal management report is not a regulated filing, not legal advice, and not tax advice.")).toBeInTheDocument();
  });

  // AC-reporting.fe-viz-reports.7 / AC-reporting.fe-viz-reports.10
  it("AC5.13.3 AC5.16.3 AC5.16.4 renders traceability appendix source, ledger, review, and identifiers", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Traceability Summary" });
    expect(screen.getAllByText("Traceability Summary").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Total Assets").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Source available").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Ledger available").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("4 evidence anchors")).toBeInTheDocument();
    expectInsideClosedAuditDetails("balance_sheet.total_assets");
    expectInsideClosedAuditDetails("posted_reconciled_journal_lines_and_manual_valuations");
    expectInsideClosedAuditDetails("bank_statement, manual_valuation_snapshot");
    expectInsideClosedAuditDetails("posted, reconciled");
    // The preview carries the detail counts, not the identifiers (#2583 S8).
    expect(expectInsideClosedAuditDetails("2 details")).toBeInstanceOf(HTMLDetailsElement);
    expect(screen.queryByText(`statement_transaction:${statementTxnId}`)).not.toBeInTheDocument();
    expectInsideClosedAuditDetails("4 anchors");
    expectInsideClosedAuditDetails("static_contract_note");
    expectInsideClosedAuditDetails("manual_only_source");
    expectInsideClosedAuditDetails("explicit_manual_input_required");
  });

  it("AC-reporting.fe-fetch-budget.7 loads the details of a traceability line only after the user opens the line", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Traceability Summary" });

    // Before the user opens a line: no evidence request and no identifier on the page.
    expect(evidenceRequests("/api/reports/package/line-details?")).toEqual([]);
    expect(evidenceRequests("/api/reports/package/manifest-entries?")).toEqual([]);
    expect(screen.queryByText(`journal_line:${journalLineId}`)).not.toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "Show evidence details for Total Assets" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);

    expect(await screen.findByText(`journal_line:${journalLineId}`)).toBeInTheDocument();
    expect(await screen.findByText(`statement_transaction:${statementTxnId}`)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Ledger evidence for Total Assets" })).toHaveTextContent(
      "Ledger evidence: 2 of 2 details",
    );
    expect(screen.getByRole("button", { name: "Hide evidence details for Total Assets" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    const requests = evidenceRequests("/api/reports/package/line-details?");
    expect(requests).toHaveLength(2);
    for (const anchor of ["source_anchor", "ledger_anchor"]) {
      const request = requests.find((path) => path.includes(`anchor=${anchor}`));
      expect(request).toBeDefined();
      const params = new URL(request!, "http://localhost").searchParams;
      // The page asks for the period of the document on screen.
      expect(Object.fromEntries(params)).toEqual({
        start_date: "2025-05-20",
        end_date: "2026-05-20",
        as_of_date: "2026-05-20",
        currency: "SGD",
        line_id: "balance_sheet.total_assets",
        anchor,
        limit: "200",
        offset: "0",
      });
    }
    // The other line stays closed, and the manifest is not read.
    expect(evidenceRequests("/api/reports/package/manifest-entries?")).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "Hide evidence details for Total Assets" }));
    expect(screen.queryByText(`journal_line:${journalLineId}`)).not.toBeInTheDocument();
  });

  it("AC-reporting.fe-fetch-budget.7 the lineage trace reuses the details that the open line loaded", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    fireEvent.click(await screen.findByRole("button", { name: "Show evidence details for Total Assets" }));
    expect(await screen.findByText(`journal_line:${journalLineId}`)).toBeInTheDocument();
    const ledgerRequests = () => evidenceRequests("/api/reports/package/line-details?").filter((path) => path.includes("anchor=ledger_anchor"));
    expect(ledgerRequests()).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Trace evidence for Total Assets" }));
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(`/api/evidence/lineage?entity_type=journal_line&entity_id=${journalLineId}&node_kind=ledger_line&direction=both&max_depth=6`),
    );
    expect(ledgerRequests()).toHaveLength(1);
  });

  it("AC-reporting.fe-fetch-budget.7 pages a long evidence list and shows a failed list", async () => {
    const ledgerIds = Array.from(
      { length: 210 },
      (_unused, index) => `journal_line:00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
    );
    mockPackageApi(readiness, frameworkPolicy, {
      ...traceabilityAppendix,
      lines: [
        {
          ...traceabilityAppendix.lines[0],
          ledger_anchor: withIdentifiers(traceabilityAppendix.lines[0].ledger_anchor, ledgerIds),
        },
      ],
    });
    const settled = mockedApiFetch.getMockImplementation()!;
    mockedApiFetch.mockImplementation((path: string, options?: RequestInit) =>
      path.startsWith("/api/reports/package/line-details?") && path.includes("anchor=source_anchor")
        ? Promise.reject(new Error("Source evidence unavailable"))
        : settled(path, options),
    );
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    fireEvent.click(await screen.findByRole("button", { name: "Show evidence details for Total Assets" }));

    const ledger = await screen.findByRole("region", { name: "Ledger evidence for Total Assets" });
    expect(await within(ledger).findByText(ledgerIds[199])).toBeInTheDocument();
    expect(within(ledger).queryByText(ledgerIds[200])).not.toBeInTheDocument();
    expect(ledger).toHaveTextContent("Ledger evidence: 200 of 210 details");
    expect(await screen.findByText("Source evidence unavailable")).toBeInTheDocument();

    fireEvent.click(within(ledger).getByRole("button", { name: "Load more ledger evidence" }));
    expect(await within(ledger).findByText(ledgerIds[209])).toBeInTheDocument();
    expect(ledger).toHaveTextContent("Ledger evidence: 210 of 210 details");
    expect(within(ledger).queryByRole("button", { name: "Load more ledger evidence" })).not.toBeInTheDocument();
    expect(
      evidenceRequests("/api/reports/package/line-details?").filter((path) => path.includes("anchor=ledger_anchor")),
    ).toEqual([expect.stringContaining("offset=0"), expect.stringContaining("offset=200")]);
  });

  it("AC-reporting.fe-fetch-budget.7 pages the authority manifest after the user opens it", async () => {
    mockPackageApi();
    const entries = Array.from({ length: 201 }, (_unused, index) => ({
      ...packageDocument().input_manifest[0],
      decision_id: `77777777-7777-4777-8777-${String(index).padStart(12, "0")}`,
    }));
    const settled = mockedApiFetch.getMockImplementation()!;
    mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
      if (!path.startsWith("/api/reports/package/manifest-entries?")) return settled(path, options);
      const offset = Number(new URL(path, "http://localhost").searchParams.get("offset"));
      return Promise.resolve({ total: entries.length, limit: 200, offset, entries: entries.slice(offset, offset + 200) });
    });
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Authority Coverage" });
    expect(evidenceRequests("/api/reports/package/manifest-entries?")).toEqual([]);

    fireEvent.click(screen.getByText("Authority manifest audit details"));
    expect(await screen.findByText(new RegExp(entries[199].decision_id))).toBeInTheDocument();
    expect(screen.queryByText(new RegExp(entries[200].decision_id))).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load more decisions" }));
    expect(await screen.findByText(new RegExp(entries[200].decision_id))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more decisions" })).not.toBeInTheDocument();
    expect(evidenceRequests("/api/reports/package/manifest-entries?")).toEqual([
      expect.stringContaining("offset=0"),
      expect.stringContaining("offset=200"),
    ]);
  });

  it("AC-reporting.fe-fetch-budget.7 shows a failed manifest and a failed trace inside their panels", async () => {
    mockPackageApi();
    const settled = mockedApiFetch.getMockImplementation()!;
    mockedApiFetch.mockImplementation((path: string, options?: RequestInit) =>
      path.startsWith("/api/reports/package/manifest-entries?") ||
      path.startsWith("/api/reports/package/line-details?")
        ? Promise.reject(new Error("Evidence page unavailable"))
        : settled(path, options),
    );
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Authority Coverage" });

    fireEvent.click(screen.getByText("Authority manifest audit details"));
    expect(await screen.findByText("Evidence page unavailable")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Trace evidence for Total Assets" }));
    const dialog = await screen.findByRole("dialog", { name: "Evidence Lineage" });
    expect(await within(dialog).findByText("Evidence page unavailable")).toBeInTheDocument();
    expect(mockedApiFetch.mock.calls.some(([path]) => String(path).startsWith("/api/evidence/lineage?"))).toBe(false);
  });

  it("AC-reporting.fe-fetch-budget.7 issues no evidence request for empty lists", async () => {
    mockPackageApi(
      {
        ...readiness,
        input_coverage: { manifest_decision_count: 0, authoritative_input_count: 0, unproven_input_count: 0 },
      },
      frameworkPolicy,
      {
        ...traceabilityAppendix,
        lines: [
          traceabilityAppendix.lines[0],
          {
            ...traceabilityAppendix.lines[1],
            source_anchor: withIdentifiers(traceabilityAppendix.lines[1].source_anchor, []),
          },
        ],
      },
    );
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Authority Coverage" });
    fireEvent.click(screen.getByText("Authority manifest audit details"));
    expect(await screen.findByText("No authority decisions are pinned for this document.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show evidence details for Package Non-Compliance Statement" }));
    expect(await screen.findByText("This line has no evidence details.")).toBeInTheDocument();
    expect(evidenceRequests("/api/reports/package/manifest-entries?")).toEqual([]);
    expect(evidenceRequests("/api/reports/package/line-details?")).toEqual([]);
  });


  // AC-reporting.fe-remainder-reports.1 / AC-reporting.fe-remainder-reports.2 / AC-reporting.fe-remainder-reports.3
  it("AC18.9.4 AC18.9.5 AC18.9.6 opens an Evidence Graph lineage panel from report traceability", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Traceability Summary" });
    fireEvent.click(screen.getByRole("button", { name: "Trace evidence for Total Assets" }));
    await screen.findByRole("dialog", { name: "Evidence Lineage" });
    // The preview has no identifiers. The trace reads the first page of the ledger details,
    // then asks the lineage graph for its first graph-compatible identifier (#2583 S8).
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(`/api/evidence/lineage?entity_type=journal_line&entity_id=${journalLineId}&node_kind=ledger_line&direction=both&max_depth=6`),
    );
    expect(evidenceRequests("/api/reports/package/line-details?")).toEqual([
      expect.stringContaining("line_id=balance_sheet.total_assets&anchor=ledger_anchor&limit=200&offset=0"),
    ]);
    expect(await screen.findByText("source_document")).toBeInTheDocument();
    expect(screen.getByText("extracted_record")).toBeInTheDocument();
    expect(screen.getByText("atomic_fact")).toBeInTheDocument();
    expect(screen.getByText("ledger_entry")).toBeInTheDocument();
    expect(screen.getByText("ledger_line")).toBeInTheDocument();
    expect(screen.getByText("report_line")).toBeInTheDocument();
    expect(screen.getByText("parsed_into")).toBeInTheDocument();
    expect(screen.getByText("aggregated_into")).toBeInTheDocument();
    expect(screen.getByText(`uploaded_document:${uploadedDocumentId}`)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close evidence lineage" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Evidence Lineage" })).not.toBeInTheDocument());
  });

  it("AC18.9.3 AC18.9.4 renders an explicit lineage blocker when a row has no graph-compatible anchor", async () => {
    mockPackageApi(readiness, frameworkPolicy, {
      ...traceabilityAppendix,
      lines: [{
        ...traceabilityAppendix.lines[0],
        ledger_anchor: withIdentifiers(traceabilityAppendix.lines[0].ledger_anchor, ["journal_line:not-a-uuid"]),
        source_anchor: withIdentifiers(traceabilityAppendix.lines[0].source_anchor, []),
      }],
    });
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Traceability Summary" });
    fireEvent.click(screen.getByRole("button", { name: "Trace evidence for Total Assets" }));
    await screen.findByRole("dialog", { name: "Evidence Lineage" });
    expect(await screen.findByText("lineage_anchor_missing")).toBeInTheDocument();
    expect(screen.getByText("No graph-compatible UUID anchor exists for this traceability row.")).toBeInTheDocument();
  });

  it("AC18.9.3 AC18.9.4 renders Evidence Graph API failures inside the lineage panel", async () => {
    mockPackageApi(readiness, frameworkPolicy, traceabilityAppendix, new Error("lineage unavailable"));
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Traceability Summary" });
    fireEvent.click(screen.getByRole("button", { name: "Trace evidence for Total Assets" }));
    await screen.findByRole("dialog", { name: "Evidence Lineage" });
    expect(await screen.findByText("lineage unavailable")).toBeInTheDocument();
  });

  it("AC18.9.4 maps source-side graph anchors into Evidence Graph lineage requests", async () => {
    const cases = [
      { identifier: `uploaded_document:${uploadedDocumentId}`, expected: `/api/evidence/lineage?entity_type=uploaded_document&entity_id=${uploadedDocumentId}&node_kind=source_document&direction=both&max_depth=6` },
      { identifier: `statement_transaction:${statementTxnId}`, expected: `/api/evidence/lineage?entity_type=bank_statement_transaction&entity_id=${statementTxnId}&node_kind=extracted_record&direction=both&max_depth=6` },
      { identifier: `atomic_transaction:${atomicTransactionId}`, expected: `/api/evidence/lineage?entity_type=atomic_transaction&entity_id=${atomicTransactionId}&node_kind=atomic_fact&direction=both&max_depth=6` },
    ];
    for (const testCase of cases) {
      mockedApiFetch.mockReset();
      mockPackageApi(readiness, frameworkPolicy, {
        ...traceabilityAppendix,
        lines: [{
          ...traceabilityAppendix.lines[0],
          ledger_anchor: withIdentifiers(traceabilityAppendix.lines[0].ledger_anchor, []),
          source_anchor: withIdentifiers(traceabilityAppendix.lines[0].source_anchor, [testCase.identifier]),
        }],
      });
      const { unmount } = renderPackagePage();
      fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
      await screen.findByRole("heading", { name: "Traceability Summary" });
      fireEvent.click(screen.getByRole("button", { name: "Trace evidence for Total Assets" }));
      await screen.findByRole("dialog", { name: "Evidence Lineage" });
      await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(testCase.expected));
      // The ledger anchor has no details, so the trace reads only the source page.
      expect(evidenceRequests("/api/reports/package/line-details?")).toEqual([expect.stringContaining("anchor=source_anchor")]);
      unmount();
    }
  });

  const sharedClient = () => new QueryClient({ defaultOptions: { queries: { staleTime: 60_000, retry: false } } });
  const withClient = (client: QueryClient) => ({ wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
  const previewRequests = () => mockedApiFetch.mock.calls.map(([path]) => String(path)).filter((p) => p.startsWith("/api/reports/package?"));
  const renderPackageWith = (client: QueryClient) => render(<PersonalReportPackagePage />, withClient(client));

  it("AC-reporting.fe-fetch-budget.5 the Reports hub and the package page share one preview request", async () => {
    mockPackageApi();
    const client = sharedClient();
    setTestUrl("/reports");
    const hub = render(<ReportsPage />, withClient(client));
    await screen.findByLabelText("Report readiness cockpit");
    await waitFor(() => expect(previewRequests()).toHaveLength(1));
    await waitFor(() => expect(screen.queryByText("Checking")).not.toBeInTheDocument());
    hub.unmount();
    setTestUrl("/reports?tab=package");
    renderPackageWith(client);
    await screen.findByRole("button", { name: "US-like" });
    expect(previewRequests()).toHaveLength(1);
  });

  it("AC-reporting.fe-fetch-budget.5 a second visit to the package page inside the stale time issues no preview request", async () => {
    mockPackageApi();
    const client = sharedClient();
    const first = renderPackageWith(client);
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("button", { name: /Generate Snapshot/i });
    first.unmount();
    mockedApiFetch.mockClear();
    renderPackageWith(client);
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("button", { name: /Generate Snapshot/i });
    expect(previewRequests()).toEqual([]);
  });

  it("AC-reporting.fe-fetch-budget.5 keeps the previous document visible, labelled with its own period, while a new date loads", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("button", { name: /Generate Snapshot/i });

    const settled = mockedApiFetch.getMockImplementation()!;
    let releasePreview: () => void = () => {};
    mockedApiFetch.mockImplementation((path: string, options?: RequestInit) =>
      path.startsWith("/api/reports/package?") ? new Promise((resolve) => { releasePreview = () => resolve(packagePreview()); }) : settled(path, options),
    );
    act(() => setTestUrl("/reports?tab=package&end=2025-03-31"));

    const notice = await screen.findByText(/The report below still shows/);
    expect(notice).toHaveTextContent("Loading the package for 2024-04-01 to 2025-03-31. The report below still shows 2025-05-20 to 2026-05-20");
    expect(screen.getByRole("heading", { name: "Reporting Basis" })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading report package" })).not.toBeInTheDocument();
    const cover = within(screen.getByRole("region", { name: "Report package cover" }));
    expect(cover.getByText("2025-05-20 to 2026-05-20")).toBeInTheDocument();
    expect(cover.queryByText(/2025-03-31/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Generate Snapshot/i })).toBeDisabled();

    await act(async () => { releasePreview(); });
    await waitFor(() => expect(screen.queryByText(/The report below still shows/)).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: /Generate Snapshot/i })).toBeEnabled());
  });

  it("AC-reporting.fe-fetch-budget.5 does not show a document of another framework while the new framework loads", async () => {
    mockPackageApi();
    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByRole("heading", { name: "Reporting Basis" });

    const settled = mockedApiFetch.getMockImplementation()!;
    mockedApiFetch.mockImplementation((path: string, options?: RequestInit) =>
      path.startsWith("/api/reports/package?framework_id=personal_hkfrs_like") ? new Promise(() => {}) : settled(path, options),
    );
    fireEvent.click(screen.getByRole("button", { name: "HK-like" }));
    await screen.findByRole("status", { name: "Loading report package" });
    expect(screen.queryByRole("heading", { name: "Reporting Basis" })).not.toBeInTheDocument();
  });

  it("AC-reporting.fe-fetch-budget.5 generating a snapshot reads the snapshot list again and marks cached previews stale", async () => {
    mockPackageApi();
    const client = sharedClient();
    renderPackageWith(client);
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    fireEvent.click(await screen.findByRole("button", { name: /Generate Snapshot/i }));
    await screen.findByText("Frozen snapshot snap-001");
    const snapshotListReads = mockedApiFetch.mock.calls.filter(([path]) => path === "/api/reports/package/snapshots");
    expect(snapshotListReads.length).toBeGreaterThanOrEqual(2);
    const current = readReportFilters(new URLSearchParams());
    const previewKey = personalReportPackageQuery({ frameworkId: "personal_us_gaap_like", reportDate: current.endDate, startDate: current.startDate }).queryKey;
    expect(client.getQueryState(previewKey)?.isInvalidated).toBe(true);
  });
});

// AC-reporting.report-integrity.3
it("discloses incomplete opening coverage in package sections", () => {
  const sections = packageDocument().sections;
  render(
    <PackageSectionCards
      sections={{
        ...sections,
        cash_flow: { ...sections.cash_flow, cash_bridge: { opening_stock_adjustment: "100", reconciles: true }, proof_state: "unproven", proof_reasons: ["opening_coverage_starts_after_period"] },
      } as unknown as PersonalReportPackageSections}
    />,
  );
  expect(screen.getByText("Known Beginning Cash")).toBeInTheDocument();
  expect(screen.getByText("Opening balance adjustment")).toBeInTheDocument();
  expect(screen.getByText(/records start after the selected period begins/i)).toBeInTheDocument();
});

// AC-reporting.net-worth-scope.15
it("#2645 labels the package net worth from the recorded scope and names each excluded class", () => {
  const sections = packageDocument().sections;
  const balance = {
    ...sections.balance_sheet,
    currency: "SGD",
    total_assets: "20360.65",
    total_liabilities: "0.00",
    excluded_holdings: [
      { asset_class: "real_estate", total_assets: "1200000.00", total_liabilities: "650000.00", net_worth: "550000.00", warnings: [] },
      { asset_class: "restricted_comp", total_assets: "42000.00", total_liabilities: "0.00", net_worth: "42000.00", warnings: [] },
    ],
  };
  const liquidSections = { ...sections, balance_sheet: balance } as unknown as PersonalReportPackageSections;
  const { unmount } = render(<PackageSectionCards sections={liquidSections} includeRestricted={false} />);
  expect(screen.getByText("Liquid net worth").nextElementSibling).toHaveTextContent("SGD 20,361");
  expect(screen.getByTestId("excluded-holdings-note")).toHaveTextContent(
    "Excludes restricted and illiquid holdings:Real Estate SGD 550,000 (net of SGD 650,000 liabilities)Restricted Comp SGD 42,000",
  );
  unmount();

  // A liquid package with no excluded class is still labelled liquid: the scope comes from the record.
  const noRows = { ...sections, balance_sheet: { ...balance, excluded_holdings: [] } } as unknown as PersonalReportPackageSections;
  const second = render(<PackageSectionCards sections={noRows} includeRestricted={false} />);
  expect(screen.getByText("Liquid net worth").nextElementSibling).toHaveTextContent("SGD 20,361");
  expect(screen.queryByTestId("excluded-holdings-note")).toBeNull();
  second.unmount();

  const third = render(<PackageSectionCards sections={noRows} includeRestricted />);
  expect(screen.getByText("Net worth").nextElementSibling).toHaveTextContent("SGD 20,361");
  expect(screen.queryByText("Liquid net worth")).toBeNull();
  third.unmount();
});

// AC-reporting.net-worth-scope.17
it("#2645 shows no bare net worth for a snapshot frozen before the scope record", () => {
  // The old shape: liquid figures, no excluded_holdings and no context.include_restricted.
  const sections = packageDocument().sections;
  const { excluded_holdings: _dropped, ...oldBalance } = { ...sections.balance_sheet, excluded_holdings: undefined };
  render(
    <PackageSectionCards
      sections={{ ...sections, balance_sheet: { ...oldBalance, currency: "SGD", total_assets: "20360.65", total_liabilities: "650000.00" } } as unknown as PersonalReportPackageSections}
    />,
  );
  expect(screen.queryByText("Net worth")).toBeNull();
  expect(screen.queryByText("Liquid net worth")).toBeNull();
  expect(screen.getByText("This snapshot does not record its restricted-holdings scope, so no net worth is shown.")).toBeInTheDocument();
});

// AC-reporting.report-integrity.3
it("keeps revoked opening evidence visible in package sections", () => {
  const sections = packageDocument().sections;
  render(
    <PackageSectionCards
      sections={{
        ...sections,
        investment_performance: { ...sections.investment_performance, holdings: [] },
        cash_flow: { ...sections.cash_flow, proof_state: "unproven", proof_reasons: ["opening_position_unproven"] },
      } as unknown as PersonalReportPackageSections}
    />,
  );
  expect(screen.getByText(/opening balance evidence needs review/i)).toBeInTheDocument();
  expect(screen.queryByText("Opening balance adjustment")).not.toBeInTheDocument();
});

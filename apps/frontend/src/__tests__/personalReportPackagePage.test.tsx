import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PersonalReportPackagePage from "@/app/(main)/reports/package/page";
import { apiDownload, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiDownload: vi.fn(),
  apiFetch: vi.fn(),
}));

const mockedApiDownload = vi.mocked(apiDownload);
const mockedApiFetch = vi.mocked(apiFetch);
const statementTxnId = "11111111-1111-4111-8111-111111111111";
const journalEntryId = "22222222-2222-4222-8222-222222222222";
const journalLineId = "33333333-3333-4333-8333-333333333333";
const uploadedDocumentId = "44444444-4444-4444-8444-444444444444";
const atomicTransactionId = "55555555-5555-4555-8555-555555555555";
const reportLineNodeId = "66666666-6666-4666-8666-666666666666";

function renderPackagePage() {
  return render(<PersonalReportPackagePage />);
}

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
  framework_policy_endpoint: "/api/reports/package/framework-policy",
  sections: [
    {
      section_id: "balance_sheet",
      label: "Balance Sheet",
      owner_epic: "EPIC-005",
      source_endpoint: "/api/reports/balance-sheet",
      status: "ready",
    },
    {
      section_id: "income_statement",
      label: "Income Statement",
      owner_epic: "EPIC-005",
      source_endpoint: "/api/reports/income-statement",
      status: "ready",
    },
    {
      section_id: "cash_flow",
      label: "Cash Flow",
      owner_epic: "EPIC-005",
      source_endpoint: "/api/reports/cash-flow",
      status: "ready",
    },
    {
      section_id: "investment_performance",
      label: "Investment Performance",
      owner_epic: "EPIC-017",
      source_endpoint: "/api/portfolio/performance/report-schedule",
      status: "ready",
    },
    {
      section_id: "annualized_income_long_term",
      label: "Annualized Income & Long-Term Compensation",
      owner_epic: "EPIC-011",
      source_endpoint: "/api/reports/package/annualized-income-schedule",
      status: "ready",
    },
    {
      section_id: "notes",
      label: "Notes & Disclosures",
      owner_epic: "EPIC-005",
      source_endpoint: "/api/reports/package/notes",
      status: "ready",
    },
    {
      section_id: "traceability_appendix",
      label: "Traceability Appendix",
      owner_epic: "EPIC-018",
      source_endpoint: "/api/reports/package/traceability",
      status: "ready",
    },
  ],
  export_contract: {
    formats: ["json", "csv"],
    csv_columns: [
      "package_id",
      "section_id",
      "line_id",
      "label",
      "amount",
      "currency",
      "source_state",
      "selected_framework_id",
      "framework_policy_result_id",
      "framework_policy_matrix_version",
      "evidence_bundle_references",
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
    calculation_basis:
      "posted_or_reconciled_income_journal_lines_trailing_12_months",
  },
  restricted_holdings: [
    {
      ticker: "SHOP-RSU",
      compensation_type: "rsu",
      fair_value: "12500.00",
      currency: "SGD",
      valuation_basis: "manual_valuation_snapshot",
      vesting_schedule: "25% annual vesting",
      unlock_date: "2027-01-01",
      liquidity_class: "restricted",
      net_worth_treatment: "excluded_from_liquid_net_worth_by_default",
    },
  ],
  restricted_fair_value_total: "12500.00",
  restricted_fair_value_total_currency: "SGD",
  net_worth_treatment: {
    liquid_net_worth_default: "exclude_restricted_holdings",
    restricted_wealth_basis: "manual_valuation_snapshot_fair_value",
    include_restricted_query:
      "/api/reports/balance-sheet?include_restricted=true",
    exclude_restricted_query:
      "/api/reports/balance-sheet?include_restricted=false",
  },
  notes: [
    "Personal management report only; not tax advice.",
    "Restricted holdings are excluded from liquid net worth by default.",
  ],
};

const readiness = {
  package_id: "personal-financial-report-package",
  state: "blocked",
  label: "Blocked",
  action_href: "/review",
  blocking_count: 2,
  blockers: [
    {
      code: "pending_review",
      label: "Pending source review",
      severity: "blocking",
      count: 1,
      reason:
        "Statement review must be completed before the package can be marked ready.",
      action_href: "/review",
    },
    {
      code: "balance_mismatch",
      label: "Balance validation mismatch",
      severity: "blocking",
      count: 1,
      reason:
        "Opening and closing balances must validate before report totals are trusted.",
      action_href: "/review",
    },
  ],
  source_summary: {
    statements: 3,
    active_accounts: 2,
    posted_journal_entries: 4,
    positions: 1,
    manual_valuations: 1,
    dividends: 1,
    market_prices: 1,
    selected_framework_id: "personal_us_gaap_like",
    framework_policy_decisions: 2,
    framework_policy_gaps: 1,
  },
  source_trust_summary: {
    source_classes: ["bank_statement", "brokerage_statement", "property_statement", "liability_statement", "esop_rsu_plan", "csv_export", "manual_record"],
    deterministic_pr_source_classes: ["bank_statement", "brokerage_statement", "property_statement", "liability_statement", "esop_rsu_plan", "csv_export", "manual_record"],
    post_merge_llm_ocr_source_classes: ["bank_statement", "brokerage_statement"],
    manual_trusted_source_classes: ["property_statement", "liability_statement", "esop_rsu_plan", "manual_record"],
    gap_source_classes: ["manual_record"],
    blocker_codes: ["missing_source_coverage", "pending_review"],
  },
  generated_at: null,
  stale_since: null,
};

const frameworkPolicy = {
  result_id:
    "policy-result:personal_us_gaap_like:2025-05-20:2026-05-20:fixture",
  framework_id: "personal_us_gaap_like",
  matrix_version: "1.0",
  report_period_start: "2025-05-20",
  report_period_end: "2026-05-20",
  generated_at: "2026-05-20",
  required_statements: [
    "balance_sheet",
    "income_statement",
    "cash_flow",
    "notes",
    "traceability_appendix",
  ],
  decisions: [
    {
      domain: "listed_security",
      recognition:
        "Recognize listed securities when brokerage evidence confirms ownership.",
      measurement: "Measure at quoted fair value when market data is fresh.",
      classification: "Marketable investment asset.",
      presentation:
        "US-like balance sheet marketable securities with unrealized gain note discipline.",
      disclosure: "Disclose price source and stale price blocker.",
      line_mappings: {
        balance_sheet: "assets.marketable_securities",
        income_statement: "income.unrealized_investment_gain_loss",
        notes: "notes.us_like_market_price_basis",
      },
      evidence_anchors: [
        {
          anchor_id: "atomic_position:abc",
          anchor_type: "atomic_position",
          source_system: "atomic_positions",
          source_id: "abc",
          description: "Brokerage holding",
        },
        {
          anchor_id: "market_price:def",
          anchor_type: "market_price",
          source_system: "stock_price",
          source_id: "def",
          description: "Synced market price",
        },
      ],
      provenance: "deterministic_matrix",
      confidence_tier: "TRUSTED",
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
      remediation:
        "Add an explicit reviewed policy rule before trusted output.",
      evidence_anchors: [
        {
          anchor_id: "atomic_position:private-token",
          anchor_type: "atomic_position",
          source_system: "atomic_positions",
          source_id: "private-token",
          description: "Unsupported private token holding",
        },
      ],
    },
  ],
};

const packageNotes = {
  section_id: "notes",
  label: "Notes & Disclosures",
  status: "ready",
  non_compliance_statement:
    "This personal management report is not a regulated filing, not legal advice, and not tax advice.",
  notes: [
    {
      note_id: "basis-of-preparation",
      label: "Basis of Preparation",
      owner_epic: "EPIC-005",
      basis: "personal_management_report_package_contract",
      source_state: "package_contract",
      applies_to_sections: ["balance_sheet", "income_statement"],
      disclosure:
        "The package assembles personal finance statements and schedules for management use.",
    },
    {
      note_id: "valuation-basis",
      label: "Valuation Basis",
      owner_epic: "EPIC-011",
      basis: "manual_valuation_component_rules",
      source_state: "manual_valuation_snapshots",
      applies_to_sections: ["balance_sheet", "annualized_income_long_term"],
      disclosure:
        "Manual valuation snapshots supply restricted compensation values.",
    },
  ],
};

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
      source_anchor: {
        state: "available",
        source_types: ["bank_statement", "manual_valuation_snapshot"],
        identifier_fields: [
          "statement_transaction_ids",
          "manual_valuation_snapshot_ids",
        ],
        identifiers: [
          `statement_transaction:${statementTxnId}`,
          "manual_valuation_snapshot:val-456",
        ],
      },
      ledger_anchor: {
        state: "available",
        entry_statuses: ["posted", "reconciled"],
        identifier_fields: ["journal_entry_ids", "journal_line_ids"],
        identifiers: [
          `journal_entry:${journalEntryId}`,
          `journal_line:${journalLineId}`,
        ],
      },
      review_state: "trusted_or_explicit_manual_input",
      confidence_tier: "TRUSTED",
      source_classes: ["bank_statement", "manual_record"],
      proof_level: "hybrid",
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
      source_anchor: {
        state: "available",
        source_types: ["package_contract"],
        identifier_fields: ["note_id"],
        identifiers: ["note:basis-of-preparation"],
      },
      ledger_anchor: {
        state: "not_applicable",
        entry_statuses: [],
        identifier_fields: [],
        identifiers: [],
      },
      review_state: "not_applicable",
      confidence_tier: "UNAVAILABLE",
      source_classes: [],
      blocker_codes: ["static_contract_note"],
    },
  ],
  completeness_warnings: [
    {
      code: "manual_only_source",
      label: "Manual-only source coverage",
      applies_to_sections: ["balance_sheet", "annualized_income_long_term"],
      state: "explicit_manual_input_required",
    },
  ],
};

const lineageResponse = {
  anchor: {
    id: "node-ledger-line",
    node_kind: "ledger_line",
    entity_type: "journal_line",
    entity_id: journalLineId,
    properties: { amount: "120.00", currency: "SGD" },
  },
  nodes: [
    {
      id: "node-uploaded-document",
      node_kind: "source_document",
      entity_type: "uploaded_document",
      entity_id: uploadedDocumentId,
      properties: { original_filename: "may-statement.csv" },
    },
    {
      id: "node-extracted-record",
      node_kind: "extracted_record",
      entity_type: "bank_statement_transaction",
      entity_id: statementTxnId,
      properties: { description: "Salary" },
    },
    {
      id: "node-atomic-fact",
      node_kind: "atomic_fact",
      entity_type: "atomic_transaction",
      entity_id: atomicTransactionId,
      properties: { amount: "120.00" },
    },
    {
      id: "node-ledger-entry",
      node_kind: "ledger_entry",
      entity_type: "journal_entry",
      entity_id: journalEntryId,
      properties: { status: "posted" },
    },
    {
      id: "node-ledger-line",
      node_kind: "ledger_line",
      entity_type: "journal_line",
      entity_id: journalLineId,
      properties: { amount: "120.00" },
    },
    {
      id: "node-report-line",
      node_kind: "report_line",
      entity_type: "package_traceability_line",
      entity_id: reportLineNodeId,
      properties: { line_id: "balance_sheet.total_assets" },
    },
  ],
  edges: [
    {
      id: "edge-parsed",
      relation: "parsed_into",
      direction: "upstream",
      depth: 4,
      from_node_id: "node-uploaded-document",
      to_node_id: "node-extracted-record",
      properties: {},
    },
    {
      id: "edge-deduped",
      relation: "deduped_into",
      direction: "upstream",
      depth: 3,
      from_node_id: "node-extracted-record",
      to_node_id: "node-atomic-fact",
      properties: {},
    },
    {
      id: "edge-posted",
      relation: "posted_as",
      direction: "upstream",
      depth: 2,
      from_node_id: "node-atomic-fact",
      to_node_id: "node-ledger-entry",
      properties: {},
    },
    {
      id: "edge-contains",
      relation: "contains",
      direction: "upstream",
      depth: 1,
      from_node_id: "node-ledger-entry",
      to_node_id: "node-ledger-line",
      properties: {},
    },
    {
      id: "edge-report",
      relation: "aggregated_into",
      direction: "downstream",
      depth: 1,
      from_node_id: "node-ledger-line",
      to_node_id: "node-report-line",
      properties: {},
    },
  ],
  blockers: [],
  max_depth: 6,
};

function mockPackageApi(
  readinessPayload = readiness,
  policyPayload = frameworkPolicy,
  traceabilityPayload: unknown = traceabilityAppendix,
  lineagePayload: unknown = lineageResponse,
) {
  mockedApiFetch.mockImplementation((path: string) => {
    if (path === "/api/reports/package/contract")
      return Promise.resolve(contract);
    if (path.startsWith("/api/reports/package/contract?framework_id=")) {
      const frameworkId = new URL(path, "http://localhost").searchParams.get(
        "framework_id",
      );
      return Promise.resolve({
        ...contract,
        selected_framework_id: frameworkId,
      });
    }
    if (path.startsWith("/api/reports/package/readiness?framework_id="))
      return Promise.resolve(readinessPayload);
    if (path.startsWith("/api/reports/package/framework-policy?framework_id="))
      return Promise.resolve(policyPayload);
    if (path.startsWith("/api/reports/package/annualized-income-schedule?"))
      return Promise.resolve(annualizedSchedule);
    if (path === "/api/reports/package/notes")
      return Promise.resolve(packageNotes);
    if (path.startsWith("/api/reports/package/traceability?"))
      return Promise.resolve(traceabilityPayload);
    if (path.startsWith("/api/evidence/lineage?"))
      return lineagePayload instanceof Error
        ? Promise.reject(lineagePayload)
        : Promise.resolve(lineagePayload);
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

describe("PersonalReportPackagePage", () => {
  afterEach(() => {
    mockedApiDownload.mockReset();
    mockedApiFetch.mockReset();
  });

  it("AC8.13.92 surfaces package API failures as a visible loading error", async () => {
    mockedApiFetch.mockRejectedValue(new Error("package contract unavailable"));

    renderPackagePage();

    expect(screen.getByText("Loading package contract...")).toBeInTheDocument();
    expect(
      await screen.findByText("package contract unavailable"),
    ).toBeInTheDocument();
  });

  it("AC20.6.1 requires explicit framework selection before loading framework-scoped package output", async () => {
    mockPackageApi();

    renderPackagePage();

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/reports/package/contract",
      ),
    );
    expect(
      await screen.findByRole("button", { name: "US-like" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "HK-like" })).toBeInTheDocument();
    expect(
      screen.getByText("Select a framework before package output is loaded."),
    ).toBeInTheDocument();
    expect(mockedApiFetch).not.toHaveBeenCalledWith(
      "/api/reports/package/readiness",
    );
    expect(screen.queryByText("Report Readiness")).not.toBeInTheDocument();
  });

  it("AC20.6.1 renders the API error when the initial package contract cannot load", async () => {
    mockedApiFetch.mockRejectedValueOnce(new Error("Contract unavailable"));

    renderPackagePage();

    expect(await screen.findByText("Contract unavailable")).toBeInTheDocument();
  });

  it("AC20.6.1 ignores the initial package contract response after unmount", async () => {
    let resolveContract!: (value: typeof contract) => void;
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/reports/package/contract") {
        return new Promise((resolve) => {
          resolveContract = resolve;
        });
      }
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    const { unmount } = renderPackagePage();

    expect(screen.getByText("Loading package contract...")).toBeInTheDocument();
    unmount();
    await act(async () => {
      resolveContract(contract);
    });
  });

  it("AC20.6.1 renders the API error when selected framework package output cannot load", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/reports/package/contract")
        return Promise.resolve(contract);
      if (path.startsWith("/api/reports/package/readiness?framework_id=")) {
        return Promise.reject(new Error("Framework package unavailable"));
      }
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));

    expect(
      await screen.findByText("Framework package unavailable"),
    ).toBeInTheDocument();
  });

  it("AC20.6.1 keeps canceled framework package requests from surfacing errors", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/reports/package/contract")
        return Promise.resolve(contract);
      if (path.startsWith("/api/reports/package/contract?framework_id=")) {
        return Promise.reject(new DOMException("Canceled", "AbortError"));
      }
      return new Promise(() => undefined);
    });

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));

    await waitFor(() =>
      expect(
        screen.queryByText("Failed to load package data."),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Loading framework package...")).toBeInTheDocument();
  });

  it("EPIC-022 #867 offers a print / save-as-PDF export of the loaded package", async () => {
    mockPackageApi();
    const printMock = vi.fn();
    window.print = printMock;

    renderPackagePage();
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));

    const printButton = await screen.findByRole("button", { name: /Print \/ Save as PDF/i });
    fireEvent.click(printButton);
    expect(printMock).toHaveBeenCalled();
  });

  it("AC20.6.1 AC20.7.1 loads readiness and policy result with the selected framework", async () => {
    mockPackageApi();

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        expect.stringContaining(
          "/api/reports/package/readiness?framework_id=personal_us_gaap_like",
        ),
        expect.objectContaining({ signal: expect.any(Object) }),
      ),
    );
    const readinessCall = mockedApiFetch.mock.calls.find(([path]) =>
      String(path).startsWith("/api/reports/package/readiness?framework_id=personal_us_gaap_like"),
    );
    expect(readinessCall).toBeTruthy();
    expectPinnedPackageDates(String(readinessCall![0]));
    expect(mockedApiFetch).toHaveBeenCalledWith(
      expect.stringContaining(
        "/api/reports/package/framework-policy?framework_id=personal_us_gaap_like",
      ),
      expect.objectContaining({ signal: expect.any(Object) }),
    );
    expect(await screen.findByText("Framework Policy")).toBeInTheDocument();
    expect(
      screen.getAllByText("personal_us_gaap_like").length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getAllByText(
        "policy-result:personal_us_gaap_like:2025-05-20:2026-05-20:fixture",
      ).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByText("assets.marketable_securities"),
    ).toBeInTheDocument();
    expect(screen.getByText("unsupported_policy_domain")).toBeInTheDocument();
  });

  it("AC20.6.1 keeps framework package sections pinned to the selected report date", async () => {
    mockPackageApi();

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByText("Framework Policy");

    fireEvent.change(screen.getByLabelText("Package report date"), {
      target: { value: "2026-04-30" },
    });

    await waitFor(() =>
      expect(
        mockedApiFetch.mock.calls.some(([path]) =>
          String(path).includes("end_date=2026-04-30"),
        ),
      ).toBe(true),
    );

    const selectedDateCalls = mockedApiFetch.mock.calls
      .map(([path]) => String(path))
      .filter((path) => path.includes("end_date=2026-04-30"));

    expect(selectedDateCalls).toEqual(
      expect.arrayContaining([
        expect.stringContaining("/api/reports/package/readiness?"),
        expect.stringContaining("/api/reports/package/framework-policy?"),
        expect.stringContaining("/api/reports/package/annualized-income-schedule?"),
        expect.stringContaining("/api/reports/package/traceability?"),
      ]),
    );
    selectedDateCalls.forEach((path) =>
      expectPackageDates(path, "2026-04-30", "2025-04-30"),
    );
  });

  it("AC20.6.1 uses calendar-year report period starts across leap years", async () => {
    mockPackageApi();

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByText("Framework Policy");

    fireEvent.change(screen.getByLabelText("Package report date"), {
      target: { value: "2024-03-01" },
    });

    await waitFor(() =>
      expect(
        mockedApiFetch.mock.calls.some(([path]) =>
          String(path).includes("end_date=2024-03-01"),
        ),
      ).toBe(true),
    );

    mockedApiFetch.mock.calls
      .map(([path]) => String(path))
      .filter((path) => path.includes("end_date=2024-03-01"))
      .forEach((path) => expectPackageDates(path, "2024-03-01", "2023-03-01"));

    fireEvent.change(screen.getByLabelText("Package report date"), {
      target: { value: "2024-02-29" },
    });

    await waitFor(() =>
      expect(
        mockedApiFetch.mock.calls.some(([path]) =>
          String(path).includes("end_date=2024-02-29"),
        ),
      ).toBe(true),
    );

    mockedApiFetch.mock.calls
      .map(([path]) => String(path))
      .filter((path) => path.includes("end_date=2024-02-29"))
      .forEach((path) => expectPackageDates(path, "2024-02-29", "2023-02-28"));
  });

  it("AC20.6.1 skips framework package reload while report date input is empty", async () => {
    mockPackageApi();

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByText("Framework Policy");

    const callCountBeforeEmptyDate = mockedApiFetch.mock.calls.length;
    fireEvent.change(screen.getByLabelText("Package report date"), {
      target: { value: "" },
    });

    expect(mockedApiFetch).toHaveBeenCalledTimes(callCountBeforeEmptyDate);
    expect(
      mockedApiFetch.mock.calls.some(([path]) =>
        String(path).includes("end_date=&"),
      ),
    ).toBe(false);
  });

  it("AC5.17.2 downloads package CSV through authenticated apiDownload", async () => {
    const createObjectUrl = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:package-csv");
    const revokeObjectUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    mockedApiDownload.mockResolvedValue({
      blob: new Blob(["package_id,section_id"], { type: "text/csv" }),
      filename: "personal-report-package.csv",
    });
    mockPackageApi();

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    const exportButton = await screen.findByRole("button", { name: "Export CSV" });
    fireEvent.click(exportButton);

    await waitFor(() => {
      expect(mockedApiDownload).toHaveBeenCalledWith(
        expect.stringContaining(
          "/api/reports/export?report_type=package&format=csv&framework_id=personal_us_gaap_like",
        ),
      );
    });
    expectPinnedPackageDates(String(mockedApiDownload.mock.calls[0][0]));

    createObjectUrl.mockRestore();
    revokeObjectUrl.mockRestore();
  });

  it("AC20.6.1 loads HK-like package output and renders empty evidence bundle metadata", async () => {
    mockPackageApi(readiness, {
      ...frameworkPolicy,
      result_id:
        "policy-result:personal_hkfrs_like:2025-05-20:2026-05-20:fixture",
      framework_id: "personal_hkfrs_like",
      decisions: [],
      gaps: [],
    });

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "HK-like" }));

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        expect.stringContaining(
          "/api/reports/package/readiness?framework_id=personal_hkfrs_like",
        ),
        expect.objectContaining({ signal: expect.any(Object) }),
      ),
    );
    expect(mockedApiFetch).toHaveBeenCalledWith(
      expect.stringContaining(
        "/api/reports/package/framework-policy?framework_id=personal_hkfrs_like",
      ),
      expect.objectContaining({ signal: expect.any(Object) }),
    );
    expect(
      screen.getByText("HK-like selected for this package."),
    ).toBeInTheDocument();
    expect(screen.getAllByText("personal_hkfrs_like").length).toBeGreaterThan(
      0,
    );
    expect(await screen.findByText("Framework Policy")).toBeInTheDocument();
    expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("none")).toBeInTheDocument();
  });

  it("AC20.6.1 ignores stale framework package responses when selection changes", async () => {
    const usSignals: AbortSignal[] = [];
    const resolveUsRequests: Array<() => void> = [];
    const hkPolicy = {
      ...frameworkPolicy,
      result_id:
        "policy-result:personal_hkfrs_like:2025-05-20:2026-05-20:fixture",
      framework_id: "personal_hkfrs_like",
      decisions: [],
      gaps: [],
    };

    mockedApiFetch.mockImplementation(
      (path: string, options?: RequestInit) => {
        if (path === "/api/reports/package/contract")
          return Promise.resolve(contract);
        if (path.includes("framework_id=personal_us_gaap_like")) {
          if (options?.signal) usSignals.push(options.signal);
          return new Promise((resolve) => {
            resolveUsRequests.push(() => {
              if (path.startsWith("/api/reports/package/contract?")) {
                resolve({
                  ...contract,
                  selected_framework_id: "personal_us_gaap_like",
                });
                return;
              }
              if (path.startsWith("/api/reports/package/readiness?")) {
                resolve(readiness);
                return;
              }
              resolve(frameworkPolicy);
            });
          });
        }
        if (path.startsWith("/api/reports/package/contract?framework_id="))
          return Promise.resolve({
            ...contract,
            selected_framework_id: "personal_hkfrs_like",
          });
        if (path.startsWith("/api/reports/package/readiness?framework_id="))
          return Promise.resolve({
            ...readiness,
            source_summary: {
              ...readiness.source_summary,
              selected_framework_id: "personal_hkfrs_like",
            },
          });
        if (path.startsWith("/api/reports/package/framework-policy?framework_id="))
          return Promise.resolve(hkPolicy);
        if (path.startsWith("/api/reports/package/annualized-income-schedule?"))
          return Promise.resolve(annualizedSchedule);
        if (path === "/api/reports/package/notes")
          return Promise.resolve(packageNotes);
        if (path.startsWith("/api/reports/package/traceability?"))
          return Promise.resolve(traceabilityAppendix);
        return Promise.reject(new Error(`Unexpected path ${path}`));
      },
    );

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await waitFor(() => expect(usSignals.length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("button", { name: "HK-like" }));

    await waitFor(() =>
      expect(usSignals.every((signal) => signal.aborted)).toBe(true),
    );
    expect(
      (
        await screen.findAllByText(
          "policy-result:personal_hkfrs_like:2025-05-20:2026-05-20:fixture",
        )
      ).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.queryByText(
        "policy-result:personal_us_gaap_like:2025-05-20:2026-05-20:fixture",
      ),
    ).not.toBeInTheDocument();

    await act(async () => {
      resolveUsRequests.forEach((resolve) => resolve());
    });
    expect(
      screen.queryByText(
        "policy-result:personal_us_gaap_like:2025-05-20:2026-05-20:fixture",
      ),
    ).not.toBeInTheDocument();
  });

  it("AC5.9.3 renders personal package contract sections from API", async () => {
    mockPackageApi();

    renderPackagePage();

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/reports/package/contract",
      ),
    );
    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByText("Balance Sheet");
    expect(screen.getByText("Personal Report Package")).toBeInTheDocument();
    expect(
      screen.getByText("personal-financial-report-package"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("balance_sheet").length).toBeGreaterThanOrEqual(
      1,
    );
    expect(screen.getByText("Balance Sheet")).toBeInTheDocument();
    expect(
      screen.getAllByText("annualized_income_long_term").length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByText("Annualized Income & Long-Term Compensation"),
    ).toBeInTheDocument();
  });

  it("AC19.5.4 renders package readiness before report package output", async () => {
    mockPackageApi();

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        expect.stringContaining(
          "/api/reports/package/readiness?framework_id=personal_us_gaap_like",
        ),
        expect.objectContaining({ signal: expect.any(Object) }),
      ),
    );
    const readinessHeading = await screen.findByText("Report Readiness");
    const balanceSheetHeading = screen.getByText("Balance Sheet");
    expect(
      readinessHeading.compareDocumentPosition(balanceSheetHeading) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      screen.getByText(
        "2 blockers must be resolved before package output is trusted.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Pending source review")).toBeInTheDocument();
    expect(screen.getByText("pending_review")).toBeInTheDocument();
    expect(screen.getByText("Balance validation mismatch")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Opening and closing balances must validate before report totals are trusted.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Journal Entries")).toBeInTheDocument();
    expect(screen.getByText("Manual Valuations")).toBeInTheDocument();
  });

  it("AC19.5.5 renders non-blocked readiness states without blocker cards", async () => {
    mockPackageApi({
      ...readiness,
      state: "generated",
      label: "Generated",
      blocking_count: 0,
      blockers: [],
    });

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await waitFor(() =>
      expect(
        screen.getByText("Current package state is generated."),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("Pending source review")).not.toBeInTheDocument();
  });

  it("AC19.9.2 renders compact source trust summary before traceability details", async () => {
    mockPackageApi();

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));

    const sourceTrust = await screen.findByText("Source Trust");
    await waitFor(() =>
      expect(screen.getAllByText("traceability_appendix").length).toBeGreaterThanOrEqual(2),
    );
    const traceability = screen.getAllByText("traceability_appendix").at(-1)!;
    expect(traceability).toBeDefined();
    expect(
      sourceTrust.compareDocumentPosition(traceability) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByText("7 classes")).toBeInTheDocument();
    expect(
      screen.getByText(
        "bank_statement, brokerage_statement, property_statement, liability_statement, esop_rsu_plan, csv_export, manual_record",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("bank_statement, brokerage_statement"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "property_statement, liability_statement, esop_rsu_plan, manual_record",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("missing_source_coverage, pending_review"),
    ).toBeInTheDocument();
  });

  it("AC5.9.4 renders export contract metadata", async () => {
    mockPackageApi();

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await waitFor(() =>
      expect(screen.getByText("Export Contract")).toBeInTheDocument(),
    );
    expect(screen.getByText("json, csv")).toBeInTheDocument();
    expect(
      screen.getByText(
        "package_id, section_id, line_id, label, amount, currency, source_state, selected_framework_id, framework_policy_result_id, framework_policy_matrix_version, evidence_bundle_references",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Framework Policy Result")).toBeInTheDocument();
    expect(screen.getAllByText("1.0").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("string")).toBeInTheDocument();
    expect(
      screen.getAllByText(/atomic_position:private-token/).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("AC5.11.2 renders annualized income schedule values and restricted treatment", async () => {
    mockPackageApi();

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await waitFor(() =>
      expect(
        screen.getByText("Annualized Income Schedule"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("SGD 137,400")).toBeInTheDocument();
    expect(screen.getByText("Salary")).toBeInTheDocument();
    expect(screen.getByText("SGD 120,000")).toBeInTheDocument();
    expect(screen.getByText("Bonus")).toBeInTheDocument();
    expect(screen.getByText("SGD 15,000")).toBeInTheDocument();
    expect(screen.getByText("Dividend")).toBeInTheDocument();
    expect(screen.getByText("SGD 2,400")).toBeInTheDocument();
    expect(screen.getByText("SHOP-RSU")).toBeInTheDocument();
    expect(screen.getByText("SGD 12,500")).toBeInTheDocument();
    expect(screen.getByText("exclude_restricted_holdings")).toBeInTheDocument();
    expect(
      screen.getByText("Personal management report only; not tax advice."),
    ).toBeInTheDocument();
  });

  it("AC5.12.3 renders package notes and disclosure basis", async () => {
    mockPackageApi();

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByText("Basis of Preparation");
    expect(
      screen.getAllByText("Notes & Disclosures").length,
    ).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Basis of Preparation")).toBeInTheDocument();
    expect(screen.getByText("Valuation Basis")).toBeInTheDocument();
    expect(screen.getByText("manual_valuation_snapshots")).toBeInTheDocument();
    expect(
      screen.getByText(
        "This personal management report is not a regulated filing, not legal advice, and not tax advice.",
      ),
    ).toBeInTheDocument();
  });

  it("AC5.13.3 AC5.16.3 AC5.16.4 renders traceability appendix source, ledger, review, confidence, and identifiers", async () => {
    mockPackageApi();

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByText("balance_sheet.total_assets");
    expect(
      screen.getAllByText("Traceability Appendix").length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByText("posted_reconciled_journal_lines_and_manual_valuations"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("bank_statement, manual_valuation_snapshot"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        `statement_transaction:${statementTxnId}, manual_valuation_snapshot:val-456`,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("posted, reconciled")).toBeInTheDocument();
    expect(
      screen.getByText(
        `journal_entry:${journalEntryId}, journal_line:${journalLineId}`,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("trusted_or_explicit_manual_input"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("TRUSTED").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("hybrid")).toBeInTheDocument();
    expect(screen.getByText("4 anchors")).toBeInTheDocument();
    expect(screen.getByText("unclassified")).toBeInTheDocument();
    expect(screen.getByText("0 anchors")).toBeInTheDocument();
    expect(screen.getByText("static_contract_note")).toBeInTheDocument();
    expect(screen.getByText("manual_only_source")).toBeInTheDocument();
    expect(
      screen.getByText("explicit_manual_input_required"),
    ).toBeInTheDocument();
  });

  it("AC18.9.4 AC18.9.5 AC18.9.6 opens an Evidence Graph lineage panel from report traceability", async () => {
    mockPackageApi();

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByText("balance_sheet.total_assets");

    fireEvent.click(
      screen.getByRole("button", {
        name: "Trace lineage for balance_sheet.total_assets",
      }),
    );

    await screen.findByRole("dialog", { name: "Evidence Lineage" });
    expect(mockedApiFetch).toHaveBeenCalledWith(
      `/api/evidence/lineage?entity_type=journal_line&entity_id=${journalLineId}&node_kind=ledger_line&direction=both&max_depth=6`,
    );
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
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Evidence Lineage" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("AC18.9.3 AC18.9.4 renders an explicit lineage blocker when a row has no graph-compatible anchor", async () => {
    mockPackageApi(readiness, frameworkPolicy, {
      ...traceabilityAppendix,
      lines: [
        {
          ...traceabilityAppendix.lines[0],
          ledger_anchor: {
            ...traceabilityAppendix.lines[0].ledger_anchor,
            identifiers: ["journal_line:not-a-uuid"],
          },
          source_anchor: {
            ...traceabilityAppendix.lines[0].source_anchor,
            identifiers: [],
          },
        },
      ],
    });

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByText("balance_sheet.total_assets");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Trace lineage for balance_sheet.total_assets",
      }),
    );

    await screen.findByRole("dialog", { name: "Evidence Lineage" });
    expect(screen.getByText("lineage_anchor_missing")).toBeInTheDocument();
    expect(
      screen.getByText(
        "No graph-compatible UUID anchor exists for this traceability row.",
      ),
    ).toBeInTheDocument();
  });

  it("AC18.9.3 AC18.9.4 renders Evidence Graph API failures inside the lineage panel", async () => {
    mockPackageApi(
      readiness,
      frameworkPolicy,
      traceabilityAppendix,
      new Error("lineage unavailable"),
    );

    renderPackagePage();

    fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
    await screen.findByText("balance_sheet.total_assets");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Trace lineage for balance_sheet.total_assets",
      }),
    );

    await screen.findByRole("dialog", { name: "Evidence Lineage" });
    expect(await screen.findByText("lineage unavailable")).toBeInTheDocument();
  });

  it("AC18.9.4 maps source-side graph anchors into Evidence Graph lineage requests", async () => {
    const cases = [
      {
        identifier: `uploaded_document:${uploadedDocumentId}`,
        expected:
          `/api/evidence/lineage?entity_type=uploaded_document&entity_id=${uploadedDocumentId}` +
          "&node_kind=source_document&direction=both&max_depth=6",
      },
      {
        identifier: `statement_transaction:${statementTxnId}`,
        expected:
          `/api/evidence/lineage?entity_type=bank_statement_transaction&entity_id=${statementTxnId}` +
          "&node_kind=extracted_record&direction=both&max_depth=6",
      },
      {
        identifier: `atomic_transaction:${atomicTransactionId}`,
        expected:
          `/api/evidence/lineage?entity_type=atomic_transaction&entity_id=${atomicTransactionId}` +
          "&node_kind=atomic_fact&direction=both&max_depth=6",
      },
    ];

    for (const testCase of cases) {
      mockedApiFetch.mockReset();
      mockPackageApi(readiness, frameworkPolicy, {
        ...traceabilityAppendix,
        lines: [
          {
            ...traceabilityAppendix.lines[0],
            ledger_anchor: {
              ...traceabilityAppendix.lines[0].ledger_anchor,
              identifiers: [],
            },
            source_anchor: {
              ...traceabilityAppendix.lines[0].source_anchor,
              identifiers: [testCase.identifier],
            },
          },
        ],
      });
      const { unmount } = renderPackagePage();

      fireEvent.click(await screen.findByRole("button", { name: "US-like" }));
      await screen.findByText("balance_sheet.total_assets");
      fireEvent.click(
        screen.getByRole("button", {
          name: "Trace lineage for balance_sheet.total_assets",
        }),
      );

      await screen.findByRole("dialog", { name: "Evidence Lineage" });
      expect(mockedApiFetch).toHaveBeenCalledWith(testCase.expected);
      unmount();
    }
  });
});

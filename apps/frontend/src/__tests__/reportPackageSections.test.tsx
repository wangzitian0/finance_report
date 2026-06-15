import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  EvidenceLineagePanel,
  PackageAnnualizedScheduleSection,
  PackageContractSections,
  PackageCover,
  PackageExportContractSection,
  PackageFrameworkPolicySection,
  PackageFrameworkSelection,
  PackageLoadingSkeleton,
  PackageNotesSection,
  PackageReadinessSection,
  PackageSetupGuidance,
  PackageSnapshotsSection,
  PackageSourceTrustSection,
  PackageTableOfContents,
  PackageTraceabilityAppendixSection,
} from "@/app/(main)/reports/package/_components/PackageSections";
import {
  evidenceBundleReferences,
  formatScheduleCurrency,
  formatSnapshotTimestamp,
  lineageAnchorForLine,
  packageTocLinks,
  renderCsv,
  sectionAnchorId,
  snapshotDownloadLabel,
} from "@/app/(main)/reports/package/_components/helpers";
import type {
  AnnualizedIncomeScheduleResponse,
  EvidenceLineageResponse,
  FrameworkPolicyResult,
  PersonalReportPackageContractResponse,
  PersonalReportPackageNotesResponse,
  PersonalReportPackageReadinessResponse,
  PersonalReportPackageSnapshotSummary,
  PersonalReportPackageTraceabilityLine,
  PersonalReportPackageTraceabilityResponse,
} from "@/lib/types";

const journalLineId = "33333333-3333-4333-8333-333333333333";

const contract: PersonalReportPackageContractResponse = {
  package_id: "personal-financial-report-package",
  version: "1.0",
  period_semantics: { decimal_serialization: "string" },
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
      section_id: "traceability_appendix",
      label: "Traceability Appendix",
      owner_epic: "EPIC-018",
      source_endpoint: "/api/reports/package/traceability",
      status: "blocked",
      blocking_issue: "#999",
    },
  ],
  export_contract: {
    formats: ["json", "csv"],
    csv_columns: ["package_id", "section_id"],
  },
};

const readiness: PersonalReportPackageReadinessResponse = {
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
      reason: "Statement review must be completed.",
      action_href: "/review",
    },
  ],
  source_summary: {
    statements: 3,
    posted_journal_entries: 4,
    manual_valuations: 1,
  },
  source_trust_summary: {
    source_classes: ["bank_statement", "manual_record"],
    deterministic_pr_source_classes: ["bank_statement"],
    post_merge_llm_ocr_source_classes: [],
    manual_trusted_source_classes: ["manual_record"],
    gap_source_classes: [],
    blocker_codes: ["pending_review"],
  },
  generated_at: null,
  stale_since: null,
};

const frameworkPolicy: FrameworkPolicyResult = {
  result_id: "policy-result:personal_us_gaap_like:fixture",
  framework_id: "personal_us_gaap_like",
  matrix_version: "1.0",
  report_period_start: "2025-05-20",
  report_period_end: "2026-05-20",
  generated_at: "2026-05-20",
  required_statements: ["balance_sheet"],
  decisions: [
    {
      domain: "listed_security",
      recognition: "r",
      measurement: "m",
      classification: "c",
      presentation: "p",
      disclosure: "d",
      line_mappings: { balance_sheet: "assets.marketable_securities" },
      evidence_anchors: [
        {
          anchor_id: "atomic_position:abc",
          anchor_type: "atomic_position",
          source_system: "atomic_positions",
          source_id: "abc",
          description: "Brokerage holding",
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
      reason: "No deterministic rule exists.",
      remediation: "Add a reviewed rule.",
      evidence_anchors: [
        {
          anchor_id: "atomic_position:private-token",
          anchor_type: "atomic_position",
          source_system: "atomic_positions",
          source_id: "private-token",
          description: "Unsupported holding",
        },
      ],
    },
  ],
};

const annualizedSchedule: AnnualizedIncomeScheduleResponse = {
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
    calculation_basis: "posted",
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
    {
      ticker: "NO-DETAILS",
      compensation_type: "option",
      fair_value: "100.00",
      currency: "SGD",
      valuation_basis: "manual_valuation_snapshot",
      liquidity_class: "restricted",
      net_worth_treatment: "excluded_from_liquid_net_worth_by_default",
    },
  ],
  restricted_fair_value_total: "12600.00",
  restricted_fair_value_total_currency: "SGD",
  net_worth_treatment: {
    liquid_net_worth_default: "exclude_restricted_holdings",
    restricted_wealth_basis: "manual_valuation_snapshot_fair_value",
    include_restricted_query: "/api/reports/balance-sheet?include_restricted=true",
    exclude_restricted_query: "/api/reports/balance-sheet?include_restricted=false",
  },
  notes: ["Personal management report only; not tax advice."],
};

const packageNotes: PersonalReportPackageNotesResponse = {
  section_id: "notes",
  label: "Notes & Disclosures",
  status: "ready",
  non_compliance_statement: "Not a regulated filing.",
  notes: [
    {
      note_id: "basis-of-preparation",
      label: "Basis of Preparation",
      owner_epic: "EPIC-005",
      basis: "package_contract",
      source_state: "package_contract",
      applies_to_sections: ["balance_sheet"],
      disclosure: "The package assembles personal finance statements.",
    },
  ],
};

const traceabilityAppendix: PersonalReportPackageTraceabilityResponse = {
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
      source_state: "posted_reconciled",
      source_anchor: {
        state: "available",
        source_types: ["bank_statement"],
        identifier_fields: ["statement_transaction_ids"],
        identifiers: ["statement_transaction:txn-1"],
      },
      ledger_anchor: {
        state: "available",
        entry_statuses: ["posted", "reconciled"],
        identifier_fields: ["journal_line_ids"],
        identifiers: [`journal_line:${journalLineId}`],
      },
      review_state: "trusted",
      confidence_tier: "TRUSTED",
      source_classes: ["bank_statement"],
      proof_level: "hybrid",
      anchor_count: 4,
      blocker_codes: ["needs_review"],
    },
    {
      line_id: "notes.statement",
      section_id: "notes",
      label: "Non-Compliance Statement",
      amount_field: null,
      currency_field: null,
      source_state: "package_contract",
      source_anchor: {
        state: "available",
        source_types: [],
        identifier_fields: [],
        identifiers: [],
      },
      ledger_anchor: {
        state: "not_applicable",
        entry_statuses: [],
        unavailable_reason: "no ledger anchor",
        identifier_fields: [],
        identifiers: [],
      },
      review_state: "not_applicable",
      confidence_tier: "UNAVAILABLE",
      source_classes: [],
      blocker_codes: [],
    },
  ],
  completeness_warnings: [
    {
      code: "manual_only_source",
      label: "Manual-only source coverage",
      applies_to_sections: ["balance_sheet"],
      state: "explicit_manual_input_required",
      remediation: "Add automated coverage.",
    },
    {
      code: "no_remediation",
      label: "Warning without remediation",
      applies_to_sections: [],
      state: "info",
    },
  ],
};

const snapshot: PersonalReportPackageSnapshotSummary = {
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
};

const lineageResponse: EvidenceLineageResponse = {
  anchor: null,
  nodes: [
    {
      id: "node-doc",
      node_kind: "source_document",
      entity_type: "uploaded_document",
      entity_id: "doc-1",
      properties: { original_filename: "may.csv" },
    },
  ],
  edges: [
    {
      id: "edge-1",
      relation: "parsed_into",
      direction: "upstream",
      depth: 1,
      from_node_id: "node-doc",
      to_node_id: "node-doc",
      properties: {},
    },
  ],
  blockers: [{ code: "blocked", message: "blocked message" }],
  max_depth: 6,
};

describe("report package extracted sections", () => {
  it("AC22.17.1 renders the package cover with id, framework, date, and period", () => {
    render(
      <PackageCover
        contract={contract}
        reportDate="2026-05-20"
        selectedFrameworkLabel="US-like"
      />,
    );
    const cover = screen.getByRole("region", { name: "Report package cover" });
    expect(within(cover).getByText("personal-financial-report-package")).toBeInTheDocument();
    expect(within(cover).getByText("US-like")).toBeInTheDocument();
    expect(within(cover).getByText("2026-05-20")).toBeInTheDocument();
    expect(within(cover).getByText("2025-05-20 to 2026-05-20")).toBeInTheDocument();
    expect(within(cover).getByText("1.0")).toBeInTheDocument();
  });

  it("AC22.17.1 falls back to a placeholder when no framework label is selected", () => {
    render(
      <PackageCover
        contract={contract}
        reportDate="2026-05-20"
        selectedFrameworkLabel={null}
      />,
    );
    expect(screen.getByText("Framework not selected")).toBeInTheDocument();
  });

  it("AC22.17.1 renders the table of contents with status badges and aria labels", () => {
    const links = packageTocLinks(contract, true);
    render(<PackageTableOfContents links={links} />);
    const nav = screen.getByRole("navigation", {
      name: "Report package table of contents",
    });
    expect(
      within(nav).getByRole("link", { name: "Reporting Framework" }),
    ).toHaveAttribute("href", "#package-framework-selection");
    expect(
      within(nav).getByRole("link", { name: "Report Readiness" }),
    ).toHaveAttribute("href", "#package-readiness");
    expect(
      within(nav).getByRole("link", { name: "Balance Sheet ready" }),
    ).toHaveAttribute("href", "#package-section-balance_sheet");
    expect(
      within(nav).getByRole("link", { name: "Export Contract" }),
    ).toHaveAttribute("href", "#package-export-contract");
  });

  it("AC22.17.1 omits framework-output links from the setup table of contents", () => {
    const links = packageTocLinks(contract, false);
    render(<PackageTableOfContents links={links} />);
    expect(
      screen.queryByRole("link", { name: "Report Readiness" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Export Contract" }),
    ).not.toBeInTheDocument();
  });

  it("renders setup guidance and the loading skeleton", () => {
    const { container } = render(
      <>
        <PackageSetupGuidance />
        <PackageLoadingSkeleton />
      </>,
    );
    expect(screen.getByRole("region", { name: "Package setup guidance" })).toBeInTheDocument();
    expect(screen.getByText("Choose a framework")).toBeInTheDocument();
    expect(
      screen.getByRole("status", { name: "Loading report package" }),
    ).toHaveAttribute("aria-busy", "true");
    expect(
      container.querySelectorAll("[data-testid='skeleton-block']").length,
    ).toBeGreaterThanOrEqual(10);
  });

  it("renders the framework selection with selected metadata and reacts to date changes", () => {
    const onReportDateChange = vi.fn();
    render(
      <PackageFrameworkSelection
        contract={contract}
        reportDate="2026-05-20"
        selectedFrameworkId="personal_us_gaap_like"
        selectedFrameworkLabel="US-like"
        frameworkButtons={<button type="button">US-like</button>}
        onReportDateChange={onReportDateChange}
      />,
    );
    expect(
      screen.getByText("US-like selected for this package."),
    ).toBeInTheDocument();
    expect(screen.getByText("personal_us_gaap_like")).toBeInTheDocument();
    expect(
      screen.getByText("personal_us_gaap_like, personal_hkfrs_like"),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Package report date"), {
      target: { value: "2026-04-30" },
    });
    expect(onReportDateChange).toHaveBeenCalledWith("2026-04-30");
  });

  it("renders the framework selection prompt when nothing is selected", () => {
    render(
      <PackageFrameworkSelection
        contract={contract}
        reportDate="2026-05-20"
        selectedFrameworkId={null}
        selectedFrameworkLabel={null}
        frameworkButtons={null}
        onReportDateChange={vi.fn()}
      />,
    );
    expect(
      screen.getByText("Select a framework before package output is loaded."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Selected Framework")).not.toBeInTheDocument();
  });

  it("renders package snapshots and wires generate, print, and download actions", () => {
    const onGenerateSnapshot = vi.fn();
    const onPrint = vi.fn();
    const onDownloadSnapshot = vi.fn();
    render(
      <PackageSnapshotsSection
        packageSnapshots={[snapshot]}
        snapshotError="boom"
        generatingSnapshot={false}
        canGenerateSnapshot
        downloadingSnapshot={null}
        onGenerateSnapshot={onGenerateSnapshot}
        onPrint={onPrint}
        onDownloadSnapshot={onDownloadSnapshot}
      />,
    );
    expect(screen.getByText("boom")).toBeInTheDocument();
    expect(screen.getByText("Trusted")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Generate Snapshot/ }));
    expect(onGenerateSnapshot).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Print \/ Save as PDF/ }));
    expect(onPrint).toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", {
        name: snapshotDownloadLabel(snapshot, "JSON"),
      }),
    );
    expect(onDownloadSnapshot).toHaveBeenCalledWith(snapshot, "json");
    fireEvent.click(
      screen.getByRole("button", {
        name: snapshotDownloadLabel(snapshot, "CSV"),
      }),
    );
    expect(onDownloadSnapshot).toHaveBeenCalledWith(snapshot, "csv");
  });

  it("renders draft snapshot status, the empty state, and a generating label", () => {
    const { rerender } = render(
      <PackageSnapshotsSection
        packageSnapshots={[{ ...snapshot, status: "draft" }]}
        snapshotError={null}
        generatingSnapshot
        canGenerateSnapshot={false}
        downloadingSnapshot="snap-001:json"
        onGenerateSnapshot={vi.fn()}
        onPrint={vi.fn()}
        onDownloadSnapshot={vi.fn()}
      />,
    );
    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByText("Generating...")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: snapshotDownloadLabel(snapshot, "JSON") }),
    ).toBeDisabled();

    rerender(
      <PackageSnapshotsSection
        packageSnapshots={[]}
        snapshotError={null}
        generatingSnapshot={false}
        canGenerateSnapshot
        downloadingSnapshot={null}
        onGenerateSnapshot={vi.fn()}
        onPrint={vi.fn()}
        onDownloadSnapshot={vi.fn()}
      />,
    );
    expect(screen.getByText("No saved package snapshots yet.")).toBeInTheDocument();
  });

  it("renders blocked readiness with blocker cards", () => {
    render(<PackageReadinessSection readiness={readiness} />);
    expect(
      screen.getByText("2 blockers must be resolved before package output is trusted."),
    ).toBeInTheDocument();
    expect(screen.getByText("Pending source review")).toBeInTheDocument();
    expect(screen.getByText("pending_review")).toBeInTheDocument();
  });

  it("renders singular blocker copy and non-blocked readiness without cards", () => {
    const { rerender } = render(
      <PackageReadinessSection
        readiness={{ ...readiness, blocking_count: 1 }}
      />,
    );
    expect(
      screen.getByText("1 blocker must be resolved before package output is trusted."),
    ).toBeInTheDocument();

    rerender(
      <PackageReadinessSection
        readiness={{
          ...readiness,
          state: "generated",
          label: "Generated",
          blocking_count: 0,
          blockers: [],
        }}
      />,
    );
    expect(
      screen.getByText("Current package state is generated."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Pending source review")).not.toBeInTheDocument();
  });

  it("renders readiness summary defaults when source fields are absent", () => {
    render(
      <PackageReadinessSection
        readiness={{ ...readiness, source_summary: {} }}
      />,
    );
    expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(3);
  });

  it("renders the source trust summary and hides it when absent", () => {
    const { rerender } = render(
      <PackageSourceTrustSection readiness={readiness} />,
    );
    expect(screen.getByText("2 classes")).toBeInTheDocument();
    expect(screen.getByText("bank_statement")).toBeInTheDocument();
    expect(screen.getByText("pending_review")).toBeInTheDocument();

    rerender(
      <PackageSourceTrustSection
        readiness={{ ...readiness, source_trust_summary: undefined }}
      />,
    );
    expect(
      screen.queryByLabelText("Source trust summary"),
    ).not.toBeInTheDocument();
  });

  it("renders the source trust summary without blocker codes", () => {
    render(
      <PackageSourceTrustSection
        readiness={{
          ...readiness,
          source_trust_summary: {
            ...readiness.source_trust_summary!,
            blocker_codes: [],
          },
        }}
      />,
    );
    expect(screen.queryByText("Blocker Codes")).not.toBeInTheDocument();
  });

  it("renders framework policy decisions and gaps", () => {
    render(<PackageFrameworkPolicySection frameworkPolicy={frameworkPolicy} />);
    expect(screen.getByText("listed_security")).toBeInTheDocument();
    expect(screen.getByText("assets.marketable_securities")).toBeInTheDocument();
    expect(screen.getByText("unsupported_policy_domain")).toBeInTheDocument();
    expect(screen.getByText("No deterministic rule exists.")).toBeInTheDocument();
  });

  it("renders contract sections with and without follow-up issues", () => {
    render(<PackageContractSections contract={contract} />);
    expect(
      screen.getByRole("heading", { name: "Balance Sheet" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Traceability Appendix" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Follow-up")).toBeInTheDocument();
    expect(screen.getByText("#999")).toBeInTheDocument();
  });

  it("renders the annualized income schedule including optional holding rows", () => {
    render(
      <PackageAnnualizedScheduleSection annualizedSchedule={annualizedSchedule} />,
    );
    expect(screen.getByText("SGD 137,400")).toBeInTheDocument();
    expect(screen.getByText("SGD 120,000")).toBeInTheDocument();
    expect(screen.getByText("SHOP-RSU")).toBeInTheDocument();
    expect(screen.getByText("Vesting")).toBeInTheDocument();
    expect(screen.getByText("Unlock")).toBeInTheDocument();
    expect(screen.getByText("NO-DETAILS")).toBeInTheDocument();
    expect(screen.getByText("exclude_restricted_holdings")).toBeInTheDocument();
    expect(
      screen.getByText("Personal management report only; not tax advice."),
    ).toBeInTheDocument();
  });

  it("renders package notes", () => {
    render(<PackageNotesSection packageNotes={packageNotes} />);
    expect(screen.getByText("Basis of Preparation")).toBeInTheDocument();
    expect(screen.getByText("Not a regulated filing.")).toBeInTheDocument();
  });

  it("renders traceability appendix and opens lineage from a row", () => {
    const onOpenLineagePanel = vi.fn();
    render(
      <PackageTraceabilityAppendixSection
        traceabilityAppendix={traceabilityAppendix}
        onOpenLineagePanel={onOpenLineagePanel}
      />,
    );
    expect(screen.getByText("balance_sheet.total_assets")).toBeInTheDocument();
    expect(screen.getByText("hybrid")).toBeInTheDocument();
    expect(screen.getByText("4 anchors")).toBeInTheDocument();
    expect(screen.getByText("needs_review")).toBeInTheDocument();
    // Second line exercises fallback branches (unclassified, 0 anchors, no blockers,
    // empty source types/identifiers, unavailable ledger reason).
    expect(screen.getByText("unclassified")).toBeInTheDocument();
    expect(screen.getByText("0 anchors")).toBeInTheDocument();
    expect(screen.getByText("no ledger anchor")).toBeInTheDocument();
    expect(screen.getByText("Add automated coverage.")).toBeInTheDocument();
    expect(screen.getByText("Warning without remediation")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "Trace lineage for balance_sheet.total_assets",
      }),
    );
    expect(onOpenLineagePanel).toHaveBeenCalledWith(
      traceabilityAppendix.lines[0],
    );
  });

  it("renders export contract metadata and an empty evidence fallback", () => {
    const { rerender } = render(
      <PackageExportContractSection
        contract={contract}
        frameworkPolicy={frameworkPolicy}
        evidenceReferences={["atomic_position:abc"]}
      />,
    );
    expect(screen.getByText("json, csv")).toBeInTheDocument();
    expect(screen.getByText("package_id, section_id")).toBeInTheDocument();
    expect(screen.getByText("atomic_position:abc")).toBeInTheDocument();

    rerender(
      <PackageExportContractSection
        contract={contract}
        frameworkPolicy={frameworkPolicy}
        evidenceReferences={[]}
      />,
    );
    expect(screen.getByText("none")).toBeInTheDocument();
  });

  it("renders the evidence lineage panel loading, error, content, and close states", () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <EvidenceLineagePanel
        line={traceabilityAppendix.lines[0]}
        response={null}
        isLoading
        error={null}
        onClose={onClose}
      />,
    );
    expect(screen.getByText("Loading evidence lineage...")).toBeInTheDocument();

    rerender(
      <EvidenceLineagePanel
        line={traceabilityAppendix.lines[0]}
        response={null}
        isLoading={false}
        error="lineage unavailable"
        onClose={onClose}
      />,
    );
    expect(screen.getByText("lineage unavailable")).toBeInTheDocument();

    rerender(
      <EvidenceLineagePanel
        line={traceabilityAppendix.lines[0]}
        response={lineageResponse}
        isLoading={false}
        error={null}
        onClose={onClose}
      />,
    );
    expect(screen.getByText("blocked")).toBeInTheDocument();
    expect(screen.getByText("blocked message")).toBeInTheDocument();
    expect(screen.getByText("source_document")).toBeInTheDocument();
    expect(screen.getByText("parsed_into")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close evidence lineage" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("renders the evidence lineage panel without blockers", () => {
    render(
      <EvidenceLineagePanel
        line={traceabilityAppendix.lines[0]}
        response={{ ...lineageResponse, blockers: [] }}
        isLoading={false}
        error={null}
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByText("blocked message")).not.toBeInTheDocument();
    expect(screen.getByText("Nodes")).toBeInTheDocument();
  });
});

describe("report package section helpers", () => {
  it("formats schedule currency without non-breaking spaces", () => {
    const formatted = formatScheduleCurrency("137400.00", "SGD");
    expect(formatted).toBe("SGD 137,400");
    expect(formatted).not.toContain(" ");
  });

  it("renders CSV joins and an empty fallback", () => {
    expect(renderCsv(["a", "b"])).toBe("a, b");
    expect(renderCsv([])).toBe("none");
    expect(renderCsv(undefined)).toBe("none");
  });

  it("derives unique sorted evidence bundle references", () => {
    expect(evidenceBundleReferences(frameworkPolicy)).toEqual([
      "atomic_position:abc",
      "atomic_position:private-token",
    ]);
  });

  it("builds section anchor ids", () => {
    expect(sectionAnchorId("balance_sheet")).toBe("package-section-balance_sheet");
  });

  it("formats snapshot timestamps with valid, missing, and invalid fallbacks", () => {
    expect(formatSnapshotTimestamp("2026-05-20T12:00:00Z")).toContain("2026");
    expect(formatSnapshotTimestamp(null)).toBe("Not recorded");
    expect(formatSnapshotTimestamp(undefined)).toBe("Not recorded");
    expect(formatSnapshotTimestamp("not-a-date")).toBe("not-a-date");
  });

  it("builds a descriptive snapshot download label", () => {
    expect(snapshotDownloadLabel(snapshot, "JSON")).toBe(
      "Download JSON snapshot snap-001 for US-like 2025-05-20 to 2026-05-20",
    );
    expect(
      snapshotDownloadLabel({ ...snapshot, framework_id: "unknown" }, "CSV"),
    ).toBe("Download CSV snapshot snap-001 for unknown 2025-05-20 to 2026-05-20");
  });

  it("derives a lineage anchor or null from a traceability line", () => {
    expect(lineageAnchorForLine(traceabilityAppendix.lines[0])).not.toBeNull();
    expect(lineageAnchorForLine(traceabilityAppendix.lines[1])).toBeNull();
  });
});

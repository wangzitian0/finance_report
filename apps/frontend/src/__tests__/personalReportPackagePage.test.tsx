import { render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import PersonalReportPackagePage from "@/app/(main)/reports/package/page"
import { apiFetch } from "@/lib/api"

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

const mockedApiFetch = vi.mocked(apiFetch)

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
  sections: [
    { section_id: "balance_sheet", label: "Balance Sheet", owner_epic: "EPIC-005", source_endpoint: "/api/reports/balance-sheet", status: "ready" },
    { section_id: "income_statement", label: "Income Statement", owner_epic: "EPIC-005", source_endpoint: "/api/reports/income-statement", status: "ready" },
    { section_id: "cash_flow", label: "Cash Flow", owner_epic: "EPIC-005", source_endpoint: "/api/reports/cash-flow", status: "ready" },
    { section_id: "investment_performance", label: "Investment Performance", owner_epic: "EPIC-017", source_endpoint: "/api/portfolio/performance/report-schedule", status: "ready" },
    { section_id: "annualized_income_long_term", label: "Annualized Income & Long-Term Compensation", owner_epic: "EPIC-011", source_endpoint: "/api/reports/package/annualized-income-schedule", status: "ready" },
    { section_id: "notes", label: "Notes & Disclosures", owner_epic: "EPIC-005", source_endpoint: "/api/reports/package/notes", status: "ready" },
    { section_id: "traceability_appendix", label: "Traceability Appendix", owner_epic: "EPIC-018", source_endpoint: "/api/reports/package/traceability", status: "planned" },
  ],
  export_contract: {
    formats: ["json", "csv"],
    csv_columns: ["package_id", "section_id", "line_id", "label", "amount", "currency", "source_state"],
  },
}

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
    include_restricted_query: "/api/reports/balance-sheet?include_restricted=true",
    exclude_restricted_query: "/api/reports/balance-sheet?include_restricted=false",
  },
  notes: [
    "Personal management report only; not tax advice.",
    "Restricted holdings are excluded from liquid net worth by default.",
  ],
}

const packageNotes = {
  section_id: "notes",
  label: "Notes & Disclosures",
  status: "ready",
  non_compliance_statement: "This personal management report is not a regulated filing, not legal advice, and not tax advice.",
  notes: [
    {
      note_id: "basis-of-preparation",
      label: "Basis of Preparation",
      owner_epic: "EPIC-005",
      basis: "personal_management_report_package_contract",
      source_state: "package_contract",
      applies_to_sections: ["balance_sheet", "income_statement"],
      disclosure: "The package assembles personal finance statements and schedules for management use.",
    },
    {
      note_id: "valuation-basis",
      label: "Valuation Basis",
      owner_epic: "EPIC-011",
      basis: "manual_valuation_component_rules",
      source_state: "manual_valuation_snapshots",
      applies_to_sections: ["balance_sheet", "annualized_income_long_term"],
      disclosure: "Manual valuation snapshots supply restricted compensation values.",
    },
  ],
}

function mockPackageApi() {
  mockedApiFetch.mockImplementation((path: string) => {
    if (path === "/api/reports/package/contract") return Promise.resolve(contract)
    if (path === "/api/reports/package/annualized-income-schedule") return Promise.resolve(annualizedSchedule)
    if (path === "/api/reports/package/notes") return Promise.resolve(packageNotes)
    return Promise.reject(new Error(`Unexpected path ${path}`))
  })
}

describe("PersonalReportPackagePage", () => {
  it("AC5.9.3 renders personal package contract sections from API", async () => {
    mockPackageApi()

    render(<PersonalReportPackagePage />)

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/reports/package/contract"))
    expect(screen.getByText("Personal Report Package")).toBeInTheDocument()
    expect(screen.getByText("personal-financial-report-package")).toBeInTheDocument()
    expect(screen.getByText("balance_sheet")).toBeInTheDocument()
    expect(screen.getByText("Balance Sheet")).toBeInTheDocument()
    expect(screen.getAllByText("annualized_income_long_term").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("Annualized Income & Long-Term Compensation")).toBeInTheDocument()
  })

  it("AC5.9.4 renders export contract metadata", async () => {
    mockPackageApi()

    render(<PersonalReportPackagePage />)

    await waitFor(() => expect(screen.getByText("Export Contract")).toBeInTheDocument())
    expect(screen.getByText("json, csv")).toBeInTheDocument()
    expect(screen.getByText("package_id, section_id, line_id, label, amount, currency, source_state")).toBeInTheDocument()
    expect(screen.getByText("string")).toBeInTheDocument()
  })

  it("AC5.11.2 renders annualized income schedule values and restricted treatment", async () => {
    mockPackageApi()

    render(<PersonalReportPackagePage />)

    await waitFor(() => expect(screen.getByText("Annualized Income Schedule")).toBeInTheDocument())
    expect(screen.getByText("SGD 137,400")).toBeInTheDocument()
    expect(screen.getByText("Salary")).toBeInTheDocument()
    expect(screen.getByText("SGD 120,000")).toBeInTheDocument()
    expect(screen.getByText("Bonus")).toBeInTheDocument()
    expect(screen.getByText("SGD 15,000")).toBeInTheDocument()
    expect(screen.getByText("Dividend")).toBeInTheDocument()
    expect(screen.getByText("SGD 2,400")).toBeInTheDocument()
    expect(screen.getByText("SHOP-RSU")).toBeInTheDocument()
    expect(screen.getByText("SGD 12,500")).toBeInTheDocument()
    expect(screen.getByText("exclude_restricted_holdings")).toBeInTheDocument()
    expect(screen.getByText("Personal management report only; not tax advice.")).toBeInTheDocument()
  })

  it("AC5.12.3 renders package notes and disclosure basis", async () => {
    mockPackageApi()

    render(<PersonalReportPackagePage />)

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/reports/package/notes"))
    expect(screen.getAllByText("Notes & Disclosures").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("Basis of Preparation")).toBeInTheDocument()
    expect(screen.getByText("Valuation Basis")).toBeInTheDocument()
    expect(screen.getByText("manual_valuation_snapshots")).toBeInTheDocument()
    expect(screen.getByText("This personal management report is not a regulated filing, not legal advice, and not tax advice.")).toBeInTheDocument()
  })
})

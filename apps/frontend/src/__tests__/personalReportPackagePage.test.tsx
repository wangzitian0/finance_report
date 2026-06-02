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
    { section_id: "annualized_income_long_term", label: "Annualized Income & Long-Term Compensation", owner_epic: "EPIC-011", source_endpoint: "/api/reports/package/annualized-income-schedule", status: "planned" },
    { section_id: "notes", label: "Notes & Disclosures", owner_epic: "EPIC-005", source_endpoint: "/api/reports/package/notes", status: "planned" },
    { section_id: "traceability_appendix", label: "Traceability Appendix", owner_epic: "EPIC-018", source_endpoint: "/api/reports/package/traceability", status: "planned" },
  ],
  export_contract: {
    formats: ["json", "csv"],
    csv_columns: ["package_id", "section_id", "line_id", "label", "amount", "currency", "source_state"],
  },
}

describe("PersonalReportPackagePage", () => {
  it("AC5.9.3 renders personal package contract sections from API", async () => {
    mockedApiFetch.mockResolvedValue(contract)

    render(<PersonalReportPackagePage />)

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/reports/package/contract"))
    expect(screen.getByText("Personal Report Package")).toBeInTheDocument()
    expect(screen.getByText("personal-financial-report-package")).toBeInTheDocument()
    expect(screen.getByText("balance_sheet")).toBeInTheDocument()
    expect(screen.getByText("Balance Sheet")).toBeInTheDocument()
    expect(screen.getByText("annualized_income_long_term")).toBeInTheDocument()
    expect(screen.getByText("Annualized Income & Long-Term Compensation")).toBeInTheDocument()
  })

  it("AC5.9.4 renders export contract metadata", async () => {
    mockedApiFetch.mockResolvedValue(contract)

    render(<PersonalReportPackagePage />)

    await waitFor(() => expect(screen.getByText("Export Contract")).toBeInTheDocument())
    expect(screen.getByText("json, csv")).toBeInTheDocument()
    expect(screen.getByText("package_id, section_id, line_id, label, amount, currency, source_state")).toBeInTheDocument()
    expect(screen.getByText("string")).toBeInTheDocument()
  })
})

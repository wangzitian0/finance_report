import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import ReportsPage from "@/app/(main)/reports/page"
import { apiOperation } from "@/lib/api-client"

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode; [key: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}))

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}))

const mockedApiOperation = vi.mocked(apiOperation)

function mapOperationToLegacy(operationId: string): string {
  if (operationId === "get_annualized_income_income_annualized_get") return "/api/income/annualized"
  if (operationId === "reconciliation_stats_reconciliation_stats_get") return "/api/reconciliation/stats"
  if (operationId === "preview_personal_report_package_reports_package_get") return "/api/reports/package?"
  return operationId
}

const mockedApiFetch = {
  mockReset: () => mockedApiOperation.mockReset(),
  mockImplementation: (fn: (path: string) => Promise<unknown>) => {
    mockedApiOperation.mockImplementation(((operationId: string) => fn(mapOperationToLegacy(operationId))) as any)
  },
  mockRejectedValue: (err: unknown) => {
    mockedApiOperation.mockRejectedValue(err)
  },
}

beforeEach(() => {
  mockedApiFetch.mockReset()
  mockedApiFetch.mockImplementation((path: string) => {
    if (path === "/api/income/annualized") {
      return Promise.resolve({ annualized_total: "120000.00", currency: "SGD" })
    }
    if (path === "/api/reconciliation/stats") {
      // match_rate is a 0–100 percentage from the backend, not a fraction.
      return Promise.resolve({ match_rate: 92, unmatched_transactions: 3 })
    }
    return Promise.resolve({})
  })
})

describe("ReportsPage", () => {
  // AC-reporting.fe-report-surfaces.8
  it("AC16.12.11 renders the four front reports and the More reports with links", async () => {
    render(<ReportsPage />)

    expect(screen.getByText("Balance Sheet")).toBeInTheDocument()
    expect(screen.getByText("Income Statement")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Balance Sheet/i })).toHaveAttribute("href", "/reports/balance-sheet")
    expect(screen.getByRole("link", { name: /Income Statement/i })).toHaveAttribute("href", "/reports/income-statement")

    fireEvent.click(screen.getByRole("button", { name: /More reports/i }))
    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())
    expect(screen.getByText("Personal Report Package")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Personal Report Package/i })).toHaveAttribute("href", "/reports/package")
    expect(screen.getByRole("link", { name: /Cash Flow Statement/i })).toHaveAttribute("href", "/reports/cash-flow")
  })

  // AC-reporting.fe-report-surfaces.9
  it("AC16.12.12 displays accounting equation section", () => {
    render(<ReportsPage />)

    expect(screen.getByText("Accounting Equation")).toBeInTheDocument()
    expect(screen.getByText("Assets")).toBeInTheDocument()
    expect(screen.getByText("Liabilities")).toBeInTheDocument()
    expect(screen.getByText("Equity")).toBeInTheDocument()
  })

  it("falls back to placeholders when the live figures fail to load", async () => {
    mockedApiFetch.mockReset()
    mockedApiFetch.mockRejectedValue(new Error("offline"))

    render(<ReportsPage />)

    // The cockpit still renders all four blocks; stat values degrade to "—".
    await waitFor(() => expect(screen.getByText("Annualized Income")).toBeInTheDocument())
    expect(screen.getByText("Reconciliation coverage")).toBeInTheDocument()
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1)
  })

  it("AC16.23.5 renders SVG icons for report cards (no emoji)", () => {
    render(<ReportsPage />)

    const emojiChars = ["📊", "📈", "💰"]
    emojiChars.forEach((emoji) => {
      expect(screen.queryByText(emoji)).toBeNull()
    })

    const svgs = document.querySelectorAll("svg")
    expect(svgs.length).toBeGreaterThanOrEqual(4)
  })

  it("reuses annualized income from the personal report package without a duplicate /api/income/annualized request", async () => {
    mockedApiFetch.mockReset()
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/reconciliation/stats") {
        return Promise.resolve({ match_rate: 100, unmatched_transactions: 0 })
      }
      if (path === "/api/reports/package?") {
        return Promise.resolve({
          readiness: {
            state: "blocked",
            label: "Blocked",
            action_href: "/attention",
            blocking_count: 1,
            blockers: [{ code: "b1", label: "Blocker 1", count: 1, reason: "Needs review" }],
            input_coverage: { manifest_decision_count: 2, unproven_input_count: 1 },
          },
          sections: {
            annualized_income_long_term: {
              income: {
                annualized_salary: "100000.00",
                annualized_bonus: "20000.00",
                annualized_dividend: "0.00",
                annualized_total: "120000.00",
                currency: "SGD",
              },
            },
          },
        })
      }
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })

    render(<ReportsPage />)

    await waitFor(() => expect(screen.getByText("SGD 120,000.00")).toBeInTheDocument())
    const annualizedCalls = mockedApiOperation.mock.calls.filter(
      ([op]) => op === "get_annualized_income_income_annualized_get",
    )
    expect(annualizedCalls).toHaveLength(0)
  })

  it("renders statement view switcher tabs, period presets, and currency filter that persist to sessionStorage", () => {
    window.sessionStorage.removeItem("finance_report.cockpit_period")
    render(<ReportsPage />)

    const tablist = screen.getByRole("tablist", { name: "Statement view switcher" })
    expect(tablist).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true")
    expect(screen.getByRole("tab", { name: "Balance Sheet" })).toHaveAttribute("href", "/reports/balance-sheet")
    expect(screen.getByRole("tab", { name: "Income Statement" })).toHaveAttribute("href", "/reports/income-statement")
    expect(screen.getByRole("tab", { name: "Cash Flow" })).toHaveAttribute("href", "/reports/cash-flow")
    expect(screen.getByRole("tab", { name: "Report Package" })).toHaveAttribute("href", "/reports/package")

    const periodGroup = screen.getByRole("group", { name: "Reporting period" })
    expect(periodGroup).toBeInTheDocument()
    for (const preset of ["1M", "1Q", "1Y", "YTD", "3Y", "All"]) {
      expect(screen.getByRole("button", { name: `Period ${preset}` })).toBeInTheDocument()
    }

    fireEvent.click(screen.getByRole("button", { name: "Period YTD" }))
    expect(window.sessionStorage.getItem("finance_report.cockpit_period")).toBe("YTD")

    const currencySelect = screen.getByLabelText("Currency")
    expect(currencySelect).toHaveValue("SGD")
    fireEvent.change(currencySelect, { target: { value: "USD" } })
    expect(currencySelect).toHaveValue("USD")
    window.sessionStorage.removeItem("finance_report.cockpit_period")
  })
})

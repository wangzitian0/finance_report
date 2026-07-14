import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import ReportsPage from "@/app/(main)/reports/page"
import { apiFetch } from "@/lib/api"

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

const mockedApiFetch = vi.mocked(apiFetch)

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
})

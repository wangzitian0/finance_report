import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import ReportsPage from "@/app/(main)/reports/page"

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

describe("ReportsPage", () => {
  it("AC16.12.11 renders all report cards and links", () => {
    render(<ReportsPage />)

    expect(screen.getByText("Balance Sheet")).toBeInTheDocument()
    expect(screen.getByText("Income Statement")).toBeInTheDocument()
    expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument()

    expect(screen.getByRole("link", { name: /Balance Sheet/i })).toHaveAttribute("href", "/reports/balance-sheet")
    expect(screen.getByRole("link", { name: /Income Statement/i })).toHaveAttribute("href", "/reports/income-statement")
    expect(screen.getByRole("link", { name: /Cash Flow Statement/i })).toHaveAttribute("href", "/reports/cash-flow")
  })

  it("AC16.12.12 displays accounting equation section", () => {
    render(<ReportsPage />)

    expect(screen.getByText("Accounting Equation")).toBeInTheDocument()
    expect(screen.getByText("Assets")).toBeInTheDocument()
    expect(screen.getByText("Liabilities")).toBeInTheDocument()
    expect(screen.getByText("Equity")).toBeInTheDocument()
  })
})

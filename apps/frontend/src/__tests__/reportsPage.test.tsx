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

    const links = screen.getAllByRole("link")
    expect(links.some((link) => link.getAttribute("href") === "/reports/balance-sheet")).toBe(true)
    expect(links.some((link) => link.getAttribute("href") === "/reports/income-statement")).toBe(true)
    expect(links.some((link) => link.getAttribute("href") === "/reports/cash-flow")).toBe(true)
  })

  it("AC16.12.12 displays accounting equation section", () => {
    render(<ReportsPage />)

    expect(screen.getByText("Accounting Equation")).toBeInTheDocument()
    expect(screen.getByText("Assets")).toBeInTheDocument()
    expect(screen.getByText("Liabilities")).toBeInTheDocument()
    expect(screen.getByText("Equity")).toBeInTheDocument()
  })
})

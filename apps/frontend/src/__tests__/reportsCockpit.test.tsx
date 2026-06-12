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
      return Promise.resolve({ match_rate: 0.92, unmatched_transactions: 3 })
    }
    return Promise.resolve({})
  })
})

describe("Reports cockpit (EPIC-022 AC22.3)", () => {
  it("AC22.3.1 leads with exactly the four everyday report blocks and their live figures", async () => {
    render(<ReportsPage />)

    for (const title of ["Balance Sheet", "Income Statement", "Annualized Income", "Reconciliation coverage"]) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }

    // Annualized Income and Reconciliation coverage surface live numbers.
    await waitFor(() => expect(screen.getByText("92% matched")).toBeInTheDocument())
    expect(screen.getByText("3 unmatched")).toBeInTheDocument()
    expect(screen.getByText(/120,000/)).toBeInTheDocument()
  })

  it("AC22.9.1 keeps the reconciliation-coverage block in the reports context, not linked into Advanced", async () => {
    render(<ReportsPage />)

    await waitFor(() => expect(screen.getByText("Reconciliation coverage")).toBeInTheDocument())
    // The 4th cockpit block must not pull an everyday user into the Advanced
    // reconciliation surface.
    expect(screen.queryByRole("link", { name: /Reconciliation coverage/i })).toBeNull()
    for (const link of screen.queryAllByRole("link")) {
      expect(link.getAttribute("href")).not.toBe("/reconciliation")
    }
  })

  it("AC22.9.3 makes the Annualized Income card's destination match its label", async () => {
    render(<ReportsPage />)

    const card = screen.getByText("Annualized Income").closest("a")
    expect(card).not.toBeNull()
    // It opens the report package, and the caption says so — no silent mismatch.
    expect(card).toHaveAttribute("href", "/reports/package")
    expect(screen.getByText(/report package/i)).toBeInTheDocument()
  })

  it("AC22.3.2 keeps Cash Flow and the Personal Report Package behind the More control", async () => {
    render(<ReportsPage />)

    // Hidden from the front section until expanded.
    expect(screen.queryByText("Cash Flow Statement")).toBeNull()
    expect(screen.queryByText("Personal Report Package")).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: /More reports/i }))

    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())
    expect(screen.getByText("Personal Report Package")).toBeInTheDocument()
  })
})

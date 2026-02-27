import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import BalanceSheetPage from "@/app/(main)/reports/balance-sheet/page"
import { apiFetch } from "@/lib/api"

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

vi.mock("@/hooks/useCurrencies", () => ({
  useCurrencies: () => ({ currencies: ["SGD", "USD"] }),
}))

vi.mock("@/lib/api", () => ({
  API_URL: "http://localhost:8000",
  apiFetch: vi.fn(),
}))

describe("BalanceSheetPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
  })

  it("AC16.14.1 renders loading and error retry states", async () => {
    mockedApiFetch.mockRejectedValue(new Error("balance failed"))

    render(<BalanceSheetPage />)

    await waitFor(() => expect(screen.getByText("balance failed")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(mockedApiFetch).toHaveBeenCalled()
  })

  it("AC16.14.2 renders totals and sections on success", async () => {
    mockedApiFetch.mockResolvedValue({
      as_of_date: "2026-02-01",
      currency: "SGD",
      assets: [{ account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: 1000 }],
      liabilities: [{ account_id: "l-root", name: "Loan", type: "LIABILITY", parent_id: null, amount: 200 }],
      equity: [{ account_id: "e-root", name: "Capital", type: "EQUITY", parent_id: null, amount: 800 }],
      total_assets: 1000,
      total_liabilities: 200,
      total_equity: 800,
      equation_delta: 0,
      is_balanced: true,
    })

    render(<BalanceSheetPage />)

    await waitFor(() => expect(screen.getByText("Balance Sheet")).toBeInTheDocument())
    expect(screen.getByRole("heading", { name: "Assets", level: 2 })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Liabilities", level: 2 })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Equity", level: 2 })).toBeInTheDocument()
    expect(screen.getAllByText(/Total:/)).toHaveLength(3)
  })

  it("AC16.14.3 toggles tree expansion controls", async () => {
    mockedApiFetch.mockResolvedValue({
      as_of_date: "2026-02-01",
      currency: "SGD",
      assets: [
        { account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: 1000 },
        { account_id: "a-child", name: "Wallet", type: "ASSET", parent_id: "a-root", amount: 100 },
      ],
      liabilities: [],
      equity: [],
      total_assets: 1000,
      total_liabilities: 0,
      total_equity: 1000,
      equation_delta: 0,
      is_balanced: true,
    })

    render(<BalanceSheetPage />)

    await waitFor(() => expect(screen.getByText("Wallet")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "–" }))
    expect(screen.queryByText("Wallet")).not.toBeInTheDocument()
  })
})

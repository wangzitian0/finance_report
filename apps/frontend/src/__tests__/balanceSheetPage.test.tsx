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

  it("AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date", async () => {
    mockedApiFetch.mockResolvedValue({
      as_of_date: "2026-02-01",
      currency: "SGD",
      assets: [{ account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: "1000" }],
      liabilities: [{ account_id: "l-root", name: "Loan", type: "LIABILITY", parent_id: null, amount: "200" }],
      equity: [{ account_id: "e-root", name: "Capital", type: "EQUITY", parent_id: null, amount: "800" }],
      total_assets: "1000",
      total_liabilities: "200",
      total_equity: "800",
      net_income: "300",
      unrealized_fx_gain_loss: "12",
      net_worth_adjustment_gain_loss: "5",
      fx_warnings: [{ type: "missing_fx_rate_partial_skip", from_currency: "USD", to_currency: "SGD", date: "2026-02-01" }],
      equation_delta: "0",
      is_balanced: true,
    })

    const { container } = render(<BalanceSheetPage />)

    await waitFor(() => expect(screen.getByText("Balance Sheet")).toBeInTheDocument())
    expect(screen.getByRole("heading", { name: "Assets", level: 2 })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Liabilities", level: 2 })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Equity", level: 2 })).toBeInTheDocument()
    expect(screen.getByText("Partial FX data used")).toBeInTheDocument()
    expect(screen.getByText("Balance Equation Detail")).toBeInTheDocument()
    expect(screen.getByText("Excluded by default")).toBeInTheDocument()
    expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("include_restricted=false"))
    expect(screen.getAllByText(/Total:/)).toHaveLength(3)

    fireEvent.click(screen.getByLabelText("Include restricted holdings"))
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenLastCalledWith(expect.stringContaining("include_restricted=true")),
    )

    const dateInput = container.querySelector('input[type="date"]')
    expect(dateInput).not.toBeNull()
    fireEvent.change(dateInput!, { target: { value: "2026-03-01" } })
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenLastCalledWith(expect.stringContaining("as_of_date=2026-03-01")),
    )
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

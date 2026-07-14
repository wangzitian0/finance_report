import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import BalanceSheetPage from "@/app/(main)/reports/balance-sheet/page"
import { apiDownload, apiFetch } from "@/lib/api"

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

const searchParamsGet = vi.fn((key: string) => {
  const params = new URLSearchParams(window.location.search)
  return params.get(key)
})

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: searchParamsGet }),
}))

vi.mock("@/hooks/useCurrencies", () => ({
  useCurrencies: () => ({ currencies: ["SGD", "USD"] }),
}))

vi.mock("@/lib/api", () => ({
  API_URL: "http://localhost:8000",
  apiDownload: vi.fn(),
  apiFetch: vi.fn(),
}))

describe("BalanceSheetPage", () => {
  const mockedApiDownload = vi.mocked(apiDownload)
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiDownload.mockReset()
    mockedApiFetch.mockReset()
    searchParamsGet.mockImplementation((key: string) => {
      const params = new URLSearchParams(window.location.search)
      return params.get(key)
    })
    window.history.replaceState({}, "", "/reports/balance-sheet")
  })

  // AC-reporting.fe-report-surfaces.10
  it("AC16.14.1 renders loading and error retry states", async () => {
    mockedApiFetch.mockRejectedValue(new Error("balance failed"))

    const { container } = render(<BalanceSheetPage />)

    expect(screen.getByRole("status", { name: "Loading balance sheet" })).toHaveAttribute("aria-busy", "true")
    expect(container.querySelectorAll("[data-testid='skeleton-block']").length).toBeGreaterThanOrEqual(12)
    expect(container.querySelector(".animate-spin")).toBeNull()

    await waitFor(() => expect(screen.getByText("balance failed")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(mockedApiFetch).toHaveBeenCalled()
  })

  // AC-reporting.fe-report-surfaces.11
  it("AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date", async () => {
    mockedApiFetch.mockResolvedValue({
      as_of_date: "2026-02-01",
      currency: "SGD",
      assets: [{ account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: "1000", provenance: "manual" }],
      liabilities: [{ account_id: "l-root", name: "Loan", type: "LIABILITY", parent_id: null, amount: "200", provenance: "derived" }],
      equity: [{ account_id: "e-root", name: "Capital", type: "EQUITY", parent_id: null, amount: "800", provenance: "imported" }],
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
    expect(screen.getByText("Manual")).toHaveAccessibleName("Provenance: Manual")
    expect(screen.getByText("Derived")).toHaveAccessibleName("Provenance: Derived")
    expect(screen.getByText("Imported")).toHaveAccessibleName("Provenance: Imported")
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

  it("AC8.13.42 honors include_restricted=true from the balance-sheet URL", async () => {
    window.history.replaceState({}, "", "/reports/balance-sheet?include_restricted=true")
    mockedApiFetch.mockResolvedValue({
      as_of_date: "2026-02-01",
      currency: "SGD",
      assets: [
        { account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: "1000", provenance: "imported" },
        {
          account_id: "restricted-root",
          name: "Four Asset ESOP",
          type: "ASSET",
          parent_id: null,
          amount: "42000",
          provenance: "manual",
        },
      ],
      liabilities: [],
      equity: [],
      total_assets: "43000",
      total_liabilities: "0",
      total_equity: "43000",
      equation_delta: "0",
      is_balanced: true,
    })

    render(<BalanceSheetPage />)

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("include_restricted=true")))
    expect(await screen.findByLabelText("Include restricted holdings")).toBeChecked()
  })

  it("AC22.3.4 opens the source drill-down when an amount is clicked", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/reports/account-lineage")) {
        return Promise.resolve({
          account_id: "a-root",
          account_name: "Cash",
          account_type: "ASSET",
          currency: "SGD",
          as_of_date: "2026-02-01",
          start_date: null,
          total: "1000.00",
          lines: [
            {
              journal_line_id: "88888888-8888-4888-8888-888888888888",
              journal_entry_id: "99999999-9999-4999-8999-999999999999",
              entry_date: "2026-01-15",
              memo: "Opening deposit",
              direction: "DEBIT",
              original_amount: "1000.00",
              original_currency: "SGD",
              amount: "1000.00",
            },
          ],
        })
      }
      return Promise.resolve({
        as_of_date: "2026-02-01",
        currency: "SGD",
        assets: [{ account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: "1000" }],
        liabilities: [],
        equity: [],
        total_assets: "1000",
        total_liabilities: "0",
        total_equity: "1000",
        equation_delta: "0",
        is_balanced: true,
      })
    })

    render(<BalanceSheetPage />)

    await waitFor(() => expect(screen.getByText("Cash")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "View source transactions for Cash" }))
    await waitFor(() => expect(screen.getByText("Opening deposit")).toBeInTheDocument())

    // Closing the drawer clears the drill target.
    fireEvent.click(screen.getByRole("button", { name: "Close panel" }))
    await waitFor(() => expect(screen.queryByText("Opening deposit")).toBeNull())
  })

  // AC-reporting.fe-report-surfaces.12
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
    fireEvent.click(screen.getByRole("button", { name: /Collapse/i }))
    expect(screen.queryByText("Wallet")).not.toBeInTheDocument()
  })

  it("#1486 surfaces the opening-balance warning and degraded confidence tier", async () => {
    mockedApiFetch.mockResolvedValue({
      as_of_date: "2026-02-01",
      currency: "SGD",
      assets: [{ account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: "-500", provenance: "imported" }],
      liabilities: [],
      equity: [],
      total_assets: "-500",
      total_liabilities: "0",
      total_equity: "0",
      confidence_tier: "LOW",
      opening_balance_warnings: [
        { type: "missing_opening_balance", message: "Record opening balances to trust this total." },
      ],
      equation_delta: "0",
      is_balanced: true,
    })

    render(<BalanceSheetPage />)

    await waitFor(() => expect(screen.getByText("Balance Sheet")).toBeInTheDocument())
    // Warning banner + CTA are shown on the report surface, not just /accounts.
    expect(screen.getByText("Opening balances not recorded")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /set opening balances/i })).toHaveAttribute("href", "/accounts")
    // The degraded aggregate tier is visible, so "✓ Balanced" is not the only signal.
    expect(screen.getByText("LOW")).toBeInTheDocument()
  })
})

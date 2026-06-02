import "@testing-library/jest-dom/vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import AccountDetailsSidebar from "@/components/accounts/AccountDetailsSidebar"
import JournalEntryDetailsModal from "@/components/journal/JournalEntryDetailsModal"
import { apiFetch } from "@/lib/api"
import type { Account, JournalEntry, JournalLine, JournalEntryListResponse } from "@/lib/types"

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }))
vi.mock("@/hooks/useFocusTrap", () => ({ useFocusTrap: vi.fn() }))

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return Wrapper
}

describe("AccountDetailsSidebar", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  it("renders nothing when account is null", () => {
    const { container } = render(<AccountDetailsSidebar account={null} isOpen={false} onClose={vi.fn()} />, { wrapper: createWrapper() })
    expect(container.firstChild).toBeNull()
  })

  it("shows account details and empty state when no transactions", async () => {
    const account: Account = { id: "a1", name: "Cash", type: "ASSET", currency: "SGD", is_active: true, balance: 1000 }
    mockedApiFetch.mockResolvedValueOnce({ items: [], total: 0 } satisfies JournalEntryListResponse)

    render(<AccountDetailsSidebar account={account} isOpen onClose={vi.fn()} />, { wrapper: createWrapper() })

    expect(screen.getByText("Cash")).toBeInTheDocument()
    expect(screen.getByText("ASSET")).toBeInTheDocument()
    expect(screen.getByText("SGD")).toBeInTheDocument()
    expect(screen.getByText(/Current Balance/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText("No recent transactions found")).toBeInTheDocument())
  })

  it("shows account code and description when provided", async () => {
    const account: Account = { id: "a2", name: "Bank", type: "ASSET", currency: "SGD", is_active: true, balance: 200, code: "1001", description: "Main account" }
    mockedApiFetch.mockResolvedValueOnce({ items: [], total: 0 } satisfies JournalEntryListResponse)

    render(<AccountDetailsSidebar account={account} isOpen onClose={vi.fn()} />, { wrapper: createWrapper() })
    await waitFor(() => expect(screen.getByText("Bank")).toBeInTheDocument())
    expect(screen.getByText("1001")).toBeInTheDocument()
    expect(screen.getByText("Main account")).toBeInTheDocument()
  })

  it("shows loading spinner while fetching and then transaction list", async () => {
    const account: Account = { id: "a3", name: "Wallet", type: "ASSET", currency: "SGD", is_active: true, balance: 50 }
    const line: JournalLine = { id: "l1", account_id: "a3", direction: "DEBIT", amount: 25, currency: "SGD" }
    const entry: JournalEntry = { id: "e1", entry_date: "2023-01-01", memo: "Pay", source_type: "bank_import", status: "posted", lines: [line], created_at: "2023-01-01T00:00:00Z" }
    mockedApiFetch.mockResolvedValueOnce({ items: [entry], total: 1 } satisfies JournalEntryListResponse)

    render(<AccountDetailsSidebar account={account} isOpen onClose={vi.fn()} />, { wrapper: createWrapper() })
    await waitFor(() => expect(screen.getByText("Pay")).toBeInTheDocument())
    expect(screen.getByText("DEBIT")).toBeInTheDocument()
  })
})

describe("JournalEntryDetailsModal", () => {
  it("renders nothing when entry is null", () => {
    const { container } = render(<JournalEntryDetailsModal entry={null} isOpen={false} onClose={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })

  it("shows entry details and memo fallback and lines with totals", () => {
    const lines: JournalLine[] = [
      { id: "l1", account_id: "a1", direction: "DEBIT", amount: 100, currency: "SGD" },
      { id: "l2", account_id: "a2", direction: "CREDIT", amount: 100, currency: "SGD" },
    ]
    const entry: JournalEntry = {
      id: "je1",
      entry_date: "2023-02-02",
      memo: "",
      source_type: "manual_entry",
      status: "posted",
      lines,
      created_at: "2023-02-02T00:00:00Z",
    }

    render(<JournalEntryDetailsModal entry={entry} isOpen onClose={vi.fn()} />)

    expect(screen.getByText(/Date/i)).toBeInTheDocument()
    expect(screen.getByText(/Status/i)).toBeInTheDocument()
    expect(screen.getByText("posted")).toBeInTheDocument()
    expect(screen.getByText("manual entry")).toBeInTheDocument()
    
    expect(screen.getByText("No memo")).toBeInTheDocument()

    
    expect(screen.getAllByText("a1").length).toBeGreaterThan(0)
    expect(screen.getAllByText("DEBIT").length).toBeGreaterThan(0)
    expect(screen.getAllByText("a2").length).toBeGreaterThan(0)
    expect(screen.getAllByText("CREDIT").length).toBeGreaterThan(0)

    
    expect(screen.getByText(/DR:/)).toBeInTheDocument()
    expect(screen.getByText(/CR:/)).toBeInTheDocument()
  })

  it("AC16.25.3 journal entry details mobile line cards expose all line fields", () => {
    const lines: JournalLine[] = [
      { id: "line-debit", account_id: "assets:cash:mobile", direction: "DEBIT", amount: 1234.56, currency: "SGD" },
      { id: "line-credit", account_id: "income:salary:mobile", direction: "CREDIT", amount: 1234.56, currency: "SGD" },
    ]
    const entry: JournalEntry = {
      id: "je-mobile",
      entry_date: "2026-06-01",
      memo: "Mobile detail entry",
      source_type: "manual_adjustment",
      status: "posted",
      lines,
      created_at: "2026-06-01T08:00:00Z",
    }

    render(<JournalEntryDetailsModal entry={entry} isOpen onClose={vi.fn()} />)

    const mobileLines = screen.getByTestId("journal-lines-mobile")
    const debitCard = within(mobileLines).getByTestId("journal-line-mobile-line-debit")
    const creditCard = within(mobileLines).getByTestId("journal-line-mobile-line-credit")

    expect(within(debitCard).getByText("assets:cash:mobile")).toBeInTheDocument()
    expect(within(debitCard).getByText("DEBIT")).toBeInTheDocument()
    expect(within(debitCard).getByText(/1,234\.56/)).toBeInTheDocument()
    expect(within(debitCard).getByText("SGD")).toBeInTheDocument()
    expect(within(creditCard).getByText("income:salary:mobile")).toBeInTheDocument()
    expect(within(creditCard).getByText("CREDIT")).toBeInTheDocument()
  })

  it("handles different statuses rendering badge variants", () => {
    const baseLine: JournalLine = { id: "l3", account_id: "a3", direction: "DEBIT", amount: 10, currency: "SGD" }
    const statuses: JournalEntry["status"][] = ["draft", "posted", "reconciled", "void"]
    statuses.forEach((status) => {
      const entry: JournalEntry = {
        id: `s-${status}`,
        entry_date: "2023-03-03",
        memo: "m",
        source_type: "import_file",
        status,
        lines: [baseLine],
        created_at: "2023-03-03T00:00:00Z",
      }
      render(<JournalEntryDetailsModal entry={entry} isOpen onClose={vi.fn()} />)
      expect(screen.getByText(status)).toBeInTheDocument()
    })
  })
})

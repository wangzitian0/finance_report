import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import UnmatchedBoard from "@/components/reconciliation/UnmatchedBoard"
import { apiFetch } from "@/lib/api"

const navigationState = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

vi.mock("next/navigation", () => ({
  useSearchParams: () => navigationState.searchParams,
}))

describe("UnmatchedBoard", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    navigationState.searchParams = new URLSearchParams()
    const storage = new Map<string, string>()
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value)
      },
      removeItem: (key: string) => {
        storage.delete(key)
      },
    })
  })

  const unmatchedItem = {
    id: "u1",
    statement_id: "s1",
    txn_date: "2026-01-11",
    description: "Card payment",
    amount: 88,
    direction: "OUT",
    status: "unmatched",
  }

  // AC-reconciliation.fe-stage2-review.9
  it("AC16.20.3 loads unmatched items and creates entry", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [
          {
            id: "u1",
            statement_id: "s1",
            txn_date: "2026-01-10",
            description: "Unknown transfer",
            amount: 120,
            direction: "OUT",
            status: "unmatched",
          },
        ],
        total: 1,
      })
      .mockResolvedValueOnce({
        id: "je1",
        entry_date: "2026-01-10",
        memo: "Generated",
        status: "draft",
        total_amount: 120,
      })
      .mockResolvedValueOnce({ items: [], total: 0 })

    render(<UnmatchedBoard />)

    await waitFor(() => expect(screen.getByRole("heading", { name: "Unmatched Transactions" })).toBeInTheDocument())
    expect(screen.getByRole("button", { name: "Create Entry" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Create Entry" }))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/reconciliation/unmatched/u1/create-entry", {
        method: "POST",
      }),
    )
  })

  it("AC22.11.3 returns attention-origin unmatched review to the attention queue", async () => {
    navigationState.searchParams = new URLSearchParams("from=attention")
    mockedApiFetch.mockResolvedValueOnce({ items: [unmatchedItem], total: 1 })

    render(<UnmatchedBoard />)

    const backLink = await screen.findByRole("link", { name: /Back to Attention queue/i })
    expect(backLink).toHaveAttribute("href", "/attention")
  })

  // AC-reconciliation.fe-stage2-review.10 / AC-reconciliation.fe-stage2-review.25
  it("AC16.20.4 AC16.31.4 supports local flag and hide actions", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      items: [
        {
          id: "u1",
          statement_id: "s1",
          txn_date: "2026-01-11",
          description: "Card payment",
          amount: 88,
          direction: "OUT",
          status: "unmatched",
        },
      ],
      total: 1,
    })

    render(<UnmatchedBoard />)

    await waitFor(() => expect(screen.getByRole("heading", { name: "Unmatched Transactions" })).toBeInTheDocument())

    expect(screen.getByText("Flags and hidden rows are local workspace triage only.")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Flag local" }))
    expect(screen.getByRole("button", { name: "Unflag local" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Hide locally" }))
    await waitFor(() => expect(screen.queryAllByText("Card payment")).toHaveLength(0))
    expect(screen.getByText("Select a transaction to review")).toBeInTheDocument()
  })

  it("AC8.13.92 updates the selected transaction when another unmatched row is clicked", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      items: [
        unmatchedItem,
        {
          ...unmatchedItem,
          id: "u2",
          description: "Broker dividend",
          amount: 42,
          direction: "IN",
          reference: "DIV-42",
        },
      ],
      total: 2,
    })

    render(<UnmatchedBoard />)

    await waitFor(() => expect(screen.getAllByText("Card payment").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole("button", { name: /Broker dividend/i }))

    expect(screen.getByText("Ref: DIV-42")).toBeInTheDocument()
    expect(screen.getAllByText("Broker dividend").length).toBeGreaterThan(0)
    expect(screen.getByText((_content, element) => element?.textContent === "2026-01-11 · Inflow")).toBeInTheDocument()
  })

  it("AC16.31.4 creates all entries only after confirming the batch action", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [
          {
            id: "u1",
            statement_id: "s1",
            txn_date: "2026-01-11",
            description: "Card payment",
            amount: 88,
            direction: "OUT",
            status: "unmatched",
          },
        ],
        total: 1,
      })
      .mockResolvedValueOnce({ created_count: 1 })
      .mockResolvedValueOnce({ items: [], total: 0 })

    render(<UnmatchedBoard />)

    await waitFor(() => expect(screen.getByRole("button", { name: "Create All Entries" })).toBeEnabled())
    fireEvent.click(screen.getByRole("button", { name: "Create All Entries" }))
    const dialog = await screen.findByRole("dialog", { name: "Create All Entries" })
    expect(dialog).toHaveTextContent("Create draft journal entries for 1 unmatched transaction?")
    fireEvent.click(screen.getByRole("button", { name: "Create Entries" }))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/reconciliation/unmatched/batch-create", {
        method: "POST",
        body: JSON.stringify({ all: true }),
      }),
    )
    expect(await screen.findByText("Created 1 journal entry from unmatched transactions.")).toBeInTheDocument()
  })

  it("clears stale batch success message on subsequent batch-create failure", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [
          {
            id: "u1",
            statement_id: "s1",
            txn_date: "2026-01-11",
            description: "Card payment",
            amount: 88,
            direction: "OUT",
            status: "unmatched",
          },
        ],
        total: 1,
      })
      .mockResolvedValueOnce({ created_count: 1 })
      .mockResolvedValueOnce({
        items: [
          {
            id: "u1",
            statement_id: "s1",
            txn_date: "2026-01-11",
            description: "Card payment",
            amount: 88,
            direction: "OUT",
            status: "unmatched",
          },
        ],
        total: 1,
      })
      .mockRejectedValueOnce(new Error("bulk failed"))

    render(<UnmatchedBoard />)

    await waitFor(() => expect(screen.getByRole("button", { name: "Create All Entries" })).toBeEnabled())
    fireEvent.click(screen.getByRole("button", { name: "Create All Entries" }))
    fireEvent.click(await screen.findByRole("button", { name: "Create Entries" }))
    expect(await screen.findByText("Created 1 journal entry from unmatched transactions.")).toBeInTheDocument()

    await waitFor(() => expect(screen.getByRole("button", { name: "Create All Entries" })).toBeEnabled())
    fireEvent.click(screen.getByRole("button", { name: "Create All Entries" }))
    fireEvent.click(await screen.findByRole("button", { name: "Create Entries" }))
    expect(await screen.findByText("bulk failed")).toBeInTheDocument()
    expect(screen.queryByText("Created 1 journal entry from unmatched transactions.")).not.toBeInTheDocument()
  })

  it("test_AC8_13_48 tolerates invalid flagged storage and refresh failures", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {})
    localStorage.setItem("finance-unmatched-flagged", "{not-json")
    mockedApiFetch.mockRejectedValueOnce(new Error("load failed"))

    render(<UnmatchedBoard />)

    expect(await screen.findByText("load failed")).toBeInTheDocument()
    expect(screen.getByText("No unmatched transactions")).toBeInTheDocument()
    warnSpy.mockRestore()
  })

  it("test_AC8_13_48 tolerates flagged storage write failures while unflagging", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {})
    vi.stubGlobal("localStorage", {
      getItem: () => JSON.stringify(["u1"]),
      setItem: () => {
        throw new Error("storage full")
      },
      removeItem: vi.fn(),
    })
    mockedApiFetch.mockResolvedValueOnce({ items: [unmatchedItem], total: 1 })

    render(<UnmatchedBoard />)

    await waitFor(() => expect(screen.getByRole("button", { name: "Unflag local" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Unflag local" }))

    await waitFor(() => expect(screen.getByRole("button", { name: "Flag local" })).toBeInTheDocument())
    expect(warnSpy).toHaveBeenCalledWith(
      "[UnmatchedBoard] Failed to save flagged state:",
      expect.any(Error),
    )
    warnSpy.mockRestore()
  })

  it("test_AC8_13_48 surfaces single-entry creation failures", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({ items: [unmatchedItem], total: 1 })
      .mockRejectedValueOnce(new Error("create failed"))

    render(<UnmatchedBoard />)

    await waitFor(() => expect(screen.getByRole("button", { name: "Create Entry" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Create Entry" }))

    expect(await screen.findByText("create failed")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Create Entry" })).toBeEnabled()
  })

  it("AC4.11.1 renders unmatched monetary amounts with Decimal-safe currency formatting", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [
          {
            id: "u-precise",
            statement_id: "s1",
            txn_date: "2026-01-11",
            description: "Precise unmatched payment",
            amount: "12345678901234567890.12",
            currency: "USD",
            direction: "OUT",
            status: "unmatched",
          },
        ],
        total: 1,
      })
      .mockResolvedValueOnce({
        id: "je-precise",
        entry_date: "2026-01-11",
        memo: "Generated",
        status: "draft",
        total_amount: "12345678901234567890.12",
        currency: "USD",
      })
      .mockResolvedValueOnce({ items: [], total: 0 })

    render(<UnmatchedBoard />)

    const formatted = "$12,345,678,901,234,567,890.12"
    await waitFor(() => expect(screen.getAllByText(formatted).length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole("button", { name: "Create Entry" }))

    expect(
      await screen.findByText((_content, element) => {
        const className = typeof element?.className === "string" ? element.className : ""
        return className.includes("success-muted") && (element?.textContent?.includes(formatted) ?? false)
      }),
    ).toBeInTheDocument()
  })
})

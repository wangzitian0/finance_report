import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import UnmatchedBoard from "@/components/reconciliation/UnmatchedBoard"
import { apiFetch } from "@/lib/api"

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

describe("UnmatchedBoard", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
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

  it("AC16.20.4 supports flag and ignore actions", async () => {
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

    fireEvent.click(screen.getByRole("button", { name: "Flag" }))
    expect(screen.getByRole("button", { name: "Unflag" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Ignore" }))
    await waitFor(() => expect(screen.queryAllByText("Card payment")).toHaveLength(0))
  })
})

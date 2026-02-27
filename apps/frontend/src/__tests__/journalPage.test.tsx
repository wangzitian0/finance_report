import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import JournalPage from "@/app/(main)/journal/page"
import { apiFetch } from "@/lib/api"

const showToastMock = vi.fn()

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock("@/components/journal/JournalEntryForm", () => ({
  default: ({ isOpen, onSuccess }: { isOpen: boolean; onSuccess: () => void }) =>
    isOpen ? <button onClick={onSuccess}>Mock Submit Entry</button> : null,
}))

vi.mock("@/components/ui/ConfirmDialog", () => ({
  default: ({ isOpen, onConfirm, onCancel }: { isOpen: boolean; onConfirm: (reason?: string) => void; onCancel: () => void }) =>
    isOpen ? (
      <div>
        <button onClick={() => onConfirm("void reason")}>Confirm Void</button>
        <button onClick={onCancel}>Cancel Void</button>
      </div>
    ) : null,
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

describe("JournalPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
    vi.stubGlobal("confirm", vi.fn(() => true))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("AC16.16.5 renders error state and retries loading entries", async () => {
    mockedApiFetch.mockRejectedValueOnce(new Error("journal failed")).mockResolvedValueOnce({ items: [] })

    render(<JournalPage />)

    await waitFor(() => expect(screen.getByText("Failed to load entries")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Retry loading journal entries" }))
    await waitFor(() => expect(screen.getByText("No journal entries yet")).toBeInTheDocument())
  })

  it("AC16.16.6 filters entries by status and renders totals", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [
          {
            id: "e1",
            memo: "Draft Memo",
            entry_date: "2026-01-01",
            status: "draft",
            source_type: "manual",
            lines: [
              { id: "l1", account_id: "a1", direction: "DEBIT", amount: 120, description: "d" },
              { id: "l2", account_id: "a2", direction: "CREDIT", amount: 120, description: "c" },
            ],
          },
        ],
      })
      .mockResolvedValueOnce({ items: [] })

    render(<JournalPage />)

    await waitFor(() => expect(screen.getByText("Draft Memo")).toBeInTheDocument())
    expect(screen.getByText("120")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "draft" }))
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("status_filter=draft")))
  })

  it("AC16.16.7 and AC16.16.8 handles draft post/delete and posted void flows", async () => {
    const entriesResponse = {
      items: [
        {
          id: "d1",
          memo: "Draft Entry",
          entry_date: "2026-01-01",
          status: "draft",
          source_type: "manual",
          lines: [
            { id: "l1", account_id: "a1", direction: "DEBIT", amount: 200, description: "d" },
            { id: "l2", account_id: "a2", direction: "CREDIT", amount: 200, description: "c" },
          ],
        },
        {
          id: "p1",
          memo: "Posted Entry",
          entry_date: "2026-01-02",
          status: "posted",
          source_type: "manual",
          lines: [
            { id: "l3", account_id: "a1", direction: "DEBIT", amount: 300, description: "d" },
            { id: "l4", account_id: "a2", direction: "CREDIT", amount: 300, description: "c" },
          ],
        },
      ],
    }

    mockedApiFetch
      .mockResolvedValueOnce(entriesResponse)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(entriesResponse)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(entriesResponse)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce({ items: [] })

    render(<JournalPage />)

    await waitFor(() => expect(screen.getByText("Draft Entry")).toBeInTheDocument())

    fireEvent.click(screen.getAllByRole("button", { name: "Post" })[0])
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/journal-entries/d1/post", { method: "POST" }))

    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0])
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/journal-entries/d1", { method: "DELETE" }))

    fireEvent.click(screen.getAllByRole("button", { name: "Void" })[0])
    fireEvent.click(screen.getByRole("button", { name: "Confirm Void" }))
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/journal-entries/p1/void", {
        method: "POST",
        body: JSON.stringify({ reason: "void reason" }),
      }),
    )
  })
})

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
  default: ({ isOpen, onConfirm, onCancel, confirmLabel }: { isOpen: boolean; onConfirm: (reason?: string) => void; onCancel: () => void; confirmLabel?: string }) =>
    isOpen ? (
      <div>
        <button onClick={() => onConfirm("void reason")}>{confirmLabel ?? "Confirm"}</button>
        <button onClick={onCancel}>Cancel</button>
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
          created_at: "2026-01-01T00:00:00Z",
          lines: [
              { id: "l1", account_id: "a1", direction: "DEBIT", amount: 120, currency: "SGD", description: "d" },
              { id: "l2", account_id: "a2", direction: "CREDIT", amount: 120, currency: "SGD", description: "c" },
            ],
          },
        ],
      })
      .mockResolvedValueOnce({ items: [] })

    render(<JournalPage />)

    await waitFor(() => expect(screen.getByText("Draft Memo")).toBeInTheDocument())
    expect(screen.getByText(/120\.00/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "draft" }))
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("status_filter=draft")))
  })

  it("AC8.13.92 opens and closes journal entry details from a list row", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [
          {
            id: "je-detail",
            memo: "Detail Entry",
            entry_date: "2026-01-03",
            status: "void",
            source_type: "bank_statement",
            created_at: "2026-01-03T00:00:00Z",
            lines: [
              { id: "l1", account_id: "cash", direction: "DEBIT", amount: 50, currency: "SGD", description: "d" },
              { id: "l2", account_id: "income", direction: "CREDIT", amount: 50, currency: "SGD", description: "c" },
            ],
          },
        ],
      })
      .mockResolvedValueOnce({ items: [] })

    render(<JournalPage />)

    fireEvent.click(await screen.findByText("Detail Entry"))
    const dialog = await screen.findByRole("dialog", { name: "Journal Entry Details" })
    expect(dialog).toHaveTextContent("bank statement")
    expect(dialog).toHaveTextContent("void")

    fireEvent.click(screen.getByRole("button", { name: "Close modal" }))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Journal Entry Details" })).not.toBeInTheDocument())
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
    fireEvent.click(screen.getByRole("button", { name: "Delete Entry" }))
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/journal-entries/d1", { method: "DELETE" }))

    fireEvent.click(screen.getAllByRole("button", { name: "Void" })[0])
    fireEvent.click(screen.getByRole("button", { name: "Void Entry" }))
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/journal-entries/p1/void", {
        method: "POST",
        body: JSON.stringify({ reason: "void reason" }),
      }),
    )
  })

  it("test_AC8_13_48 opens the entry form from header and empty state actions", async () => {
    mockedApiFetch.mockResolvedValue({ items: [] })

    render(<JournalPage />)

    await waitFor(() => expect(screen.getByText("No journal entries yet")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "New Entry" }))
    fireEvent.click(screen.getByRole("button", { name: "Mock Submit Entry" }))
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(2))

    fireEvent.click(screen.getByRole("button", { name: "Create First Entry" }))
    expect(screen.getByRole("button", { name: "Mock Submit Entry" })).toBeInTheDocument()
  })

  it("test_AC8_13_48 surfaces post failures without closing the page", async () => {
    const entriesResponse = {
      items: [
        {
          id: "d-error",
          memo: "Draft Error",
          entry_date: "2026-01-01",
          status: "draft",
          source_type: "manual",
          lines: [
            { id: "l1", account_id: "a1", direction: "DEBIT", amount: 200, description: "d" },
            { id: "l2", account_id: "a2", direction: "CREDIT", amount: 200, description: "c" },
          ],
        },
      ],
    }

    mockedApiFetch.mockResolvedValueOnce(entriesResponse).mockRejectedValueOnce(new Error("post denied"))

    render(<JournalPage />)

    await waitFor(() => expect(screen.getByText("Draft Error")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Post" }))
    await waitFor(() => expect(screen.getAllByText("post denied").length).toBeGreaterThan(0))
  })

  it("test_AC8_13_48 surfaces delete failures from the confirmation dialog", async () => {
    const entriesResponse = {
      items: [
        {
          id: "d-error",
          memo: "Draft Error",
          entry_date: "2026-01-01",
          status: "draft",
          source_type: "manual",
          lines: [
            { id: "l1", account_id: "a1", direction: "DEBIT", amount: 200, description: "d" },
            { id: "l2", account_id: "a2", direction: "CREDIT", amount: 200, description: "c" },
          ],
        },
      ],
    }

    mockedApiFetch.mockResolvedValueOnce(entriesResponse).mockRejectedValueOnce(new Error("delete denied"))

    render(<JournalPage />)

    await waitFor(() => expect(screen.getByText("Draft Error")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Delete" }))
    fireEvent.click(screen.getByRole("button", { name: "Delete Entry" }))
    await waitFor(() => expect(screen.getAllByText("delete denied").length).toBeGreaterThan(0))
  })

  it("test_AC8_13_48 covers delete and void dialog cancel plus void failure", async () => {
    const entriesResponse = {
      items: [
        {
          id: "d-cancel",
          memo: "Draft Cancel",
          entry_date: "2026-01-01",
          status: "draft",
          source_type: "manual",
          lines: [
            { id: "l1", account_id: "a1", direction: "DEBIT", amount: 100, description: "d" },
            { id: "l2", account_id: "a2", direction: "CREDIT", amount: 100, description: "c" },
          ],
        },
        {
          id: "p-error",
          memo: "Posted Error",
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

    mockedApiFetch.mockResolvedValueOnce(entriesResponse).mockRejectedValueOnce(new Error("void denied"))

    render(<JournalPage />)

    await waitFor(() => expect(screen.getByText("Draft Cancel")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Delete" }))
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(screen.queryByRole("button", { name: "Delete Entry" })).not.toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Void" }))
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(screen.queryByRole("button", { name: "Void Entry" })).not.toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Void" }))
    fireEvent.click(screen.getByRole("button", { name: "Void Entry" }))
    await waitFor(() => expect(screen.getAllByText("void denied").length).toBeGreaterThan(0))
  })
})

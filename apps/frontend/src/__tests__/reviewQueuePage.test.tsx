import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import Stage2ReviewQueuePage from "@/app/(main)/reconciliation/review-queue/page"
import { apiFetch } from "@/lib/api"

const showToastMock = vi.fn()

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock("@/components/ui/ConfirmDialog", () => ({
  default: ({ isOpen, onConfirm, onCancel, children }: { isOpen: boolean; onConfirm: (note?: string) => void; onCancel: () => void; children?: ReactNode }) =>
    isOpen ? (
      <div>
        <button onClick={() => onConfirm("resolution note")}>Confirm Resolve</button>
        <button onClick={onCancel}>Cancel Resolve</button>
        {children}
      </div>
    ) : null,
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

const queuePayload = {
  pending_matches: [
    { id: "m1", match_score: 88, status: "pending_review", created_at: "2026-01-01T00:00:00Z", description: "Grocery Store", amount: 42.50, txn_date: "2026-01-01" },
    { id: "m2", match_score: 70, status: "pending_review", created_at: "2026-01-02T00:00:00Z" },
    { id: "m3", match_score: 45, status: "pending_review", created_at: "2026-01-03T00:00:00Z" },
  ],
  consistency_checks: [
    {
      id: "c1",
      check_type: "duplicate",
      status: "pending",
      related_txn_ids: ["t1"],
      details: { message: "Duplicate transaction" },
      severity: "high",
      resolved_at: null,
      resolution_note: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ],
  has_unresolved_checks: true,
}

describe("Stage2ReviewQueuePage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
  })

  it("AC16.17.1 shows failure fallback and supports retry", async () => {
    mockedApiFetch.mockRejectedValueOnce(new Error("queue failed")).mockResolvedValueOnce(queuePayload)

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByText("Failed to load review queue")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() => expect(screen.getByText("Reconciliation Review Queue")).toBeInTheDocument())
  })

  it("AC16.17.2 shows unresolved-check warning and disables batch approval", async () => {
    mockedApiFetch.mockResolvedValueOnce(queuePayload)

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByText("Unresolved consistency checks block batch approval")).toBeInTheDocument())
    const approveButton = screen.getByRole("button", { name: "Approve Selected" })
    expect((approveButton as HTMLButtonElement).disabled).toBe(true)
    expect(approveButton.getAttribute("title")).toBe("Resolve consistency checks first")
  })

  it("AC16.17.3 performs batch reject and approve workflows", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({ ...queuePayload, consistency_checks: [], has_unresolved_checks: false })
      .mockResolvedValueOnce({ success: true, rejected_count: 1 })
      .mockResolvedValueOnce({ ...queuePayload, consistency_checks: [], has_unresolved_checks: false })
      .mockResolvedValueOnce({ success: true, approved_count: 2 })
      .mockResolvedValueOnce({ ...queuePayload, consistency_checks: [], has_unresolved_checks: false })

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByText("Reconciliation Review Queue")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Select all" }))
    fireEvent.click(screen.getByRole("button", { name: "Reject" }))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/batch-reject-matches", {
        method: "POST",
        body: JSON.stringify({ match_ids: ["m1", "m2", "m3"] }),
      }),
    )
    fireEvent.click(screen.getByRole("button", { name: "Select all" }))
    fireEvent.click(screen.getByRole("button", { name: "Approve Selected" }))
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/batch-approve-matches", {
        method: "POST",
        body: JSON.stringify({ match_ids: ["m1", "m2", "m3"] }),
      }),
    )
  })

  it("AC16.17.4 resolves consistency checks through dialog actions", async () => {
    mockedApiFetch
      .mockResolvedValueOnce(queuePayload)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(queuePayload)

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }))
    fireEvent.click(screen.getAllByRole("button", { name: "Reject" }).at(-1) as HTMLButtonElement)

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/consistency-checks/c1/resolve", {
        method: "POST",
        body: JSON.stringify({ action: "reject", note: "" }),
      }),
    )
  })

  it("ESC key closes the resolve dialog and clears state", async () => {
    mockedApiFetch.mockResolvedValueOnce(queuePayload)

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }))

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument())

    fireEvent.keyDown(document, { key: "Escape" })

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  it("toggleMatch deselects a previously selected match when clicked again", async () => {
    mockedApiFetch.mockResolvedValueOnce({ ...queuePayload, consistency_checks: [], has_unresolved_checks: false })

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByText("Reconciliation Review Queue")).toBeInTheDocument())

    const checkboxes = screen.getAllByRole("checkbox")
    fireEvent.click(checkboxes[1])

    expect(screen.getByText("1 selected")).toBeInTheDocument()

    fireEvent.click(checkboxes[1])

    expect(screen.getByText("0 selected")).toBeInTheDocument()
  })

  it("resolve dialog Approve button calls handleResolveCheck with approve action", async () => {
    mockedApiFetch
      .mockResolvedValueOnce(queuePayload)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(queuePayload)

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }))

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument())

    const noteInput = screen.getByPlaceholderText("Add resolution note...")
    fireEvent.change(noteInput, { target: { value: "looks good" } })

    fireEvent.click(screen.getByRole("button", { name: "Approve" }))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/consistency-checks/c1/resolve", {
        method: "POST",
        body: JSON.stringify({ action: "approve", note: "looks good" }),
      }),
    )
  })

  it("resolve dialog Flag button calls handleResolveCheck with flag action", async () => {
    mockedApiFetch
      .mockResolvedValueOnce(queuePayload)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(queuePayload)

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }))

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Flag" }))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/consistency-checks/c1/resolve", {
        method: "POST",
        body: JSON.stringify({ action: "flag", note: "" }),
      }),
    )
  })

  it("resolve dialog Cancel button closes dialog without API call", async () => {
    mockedApiFetch.mockResolvedValueOnce(queuePayload)

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }))

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }))

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(mockedApiFetch).toHaveBeenCalledTimes(1)
  })

  it("batch reject error shows toast", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({ ...queuePayload, consistency_checks: [], has_unresolved_checks: false })
      .mockRejectedValueOnce(new Error("Network error"))

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByText("Reconciliation Review Queue")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Select all" }))
    fireEvent.click(screen.getByRole("button", { name: "Reject" }))

    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith("Network error", "error"))
  })

  it("renders match score colors: green for high, yellow for medium, red for low", async () => {
    mockedApiFetch.mockResolvedValueOnce({ ...queuePayload, consistency_checks: [], has_unresolved_checks: false })

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByText("Reconciliation Review Queue")).toBeInTheDocument())

    const score88 = screen.getByText("88")
    expect(score88.className).toContain("text-[var(--success)]")

    const score70 = screen.getByText("70")
    expect(score70.className).toContain("text-[var(--warning)]")

    const score45 = screen.getByText("45")
    expect(score45.className).toContain("text-[var(--error)]")
  })

  it("renders description, amount, and date when available in matches", async () => {
    mockedApiFetch.mockResolvedValueOnce({ ...queuePayload, consistency_checks: [], has_unresolved_checks: false })

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByText("Reconciliation Review Queue")).toBeInTheDocument())

    expect(screen.getByText("Grocery Store")).toBeInTheDocument()
    expect(screen.getByText(/42\.50/)).toBeInTheDocument()

    const dashes = screen.getAllByText("\u2014")
    expect(dashes.length).toBeGreaterThanOrEqual(6)
  })

  it("handleResolveCheck error shows toast", async () => {
    mockedApiFetch
      .mockResolvedValueOnce(queuePayload)
      .mockRejectedValueOnce(new Error("Resolve failed"))

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }))

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Approve" }))

    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith("Resolve failed", "error"))
  })

  it("renders medium severity and transfer_pair check type labels", async () => {
    const medPayload = {
      ...queuePayload,
      consistency_checks: [
        {
          id: "c2",
          check_type: "transfer_pair",
          status: "pending",
          related_txn_ids: ["t2"],
          details: { message: "Transfer pair mismatch" },
          severity: "medium",
          resolved_at: null,
          resolution_note: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
    }
    mockedApiFetch.mockResolvedValueOnce(medPayload)

    render(<Stage2ReviewQueuePage />)

    await waitFor(() => expect(screen.getByText("MEDIUM")).toBeInTheDocument())
    expect(screen.getByText("Transfer Pair")).toBeInTheDocument()
    const severityEl = screen.getByText("MEDIUM")
    expect(severityEl.className).toContain("text-[var(--warning)]")
  })
})
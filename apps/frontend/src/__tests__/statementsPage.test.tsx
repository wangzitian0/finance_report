import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import StatementsPage from "@/app/(main)/upload/page"
import { apiOperation } from "@/lib/api-client"
import type { BankStatement } from "@/lib/types"

const showToastMock = vi.fn()
let latestUploadComplete: (() => void) | null = null

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

const routerPushMock = vi.fn()

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPushMock }),
}))

vi.mock("@/components/statements/StatementUploader", () => ({
  default: ({ onUploadComplete, kind = "all" }: { onUploadComplete: () => void; kind?: string }) => {
    latestUploadComplete = onUploadComplete
    return <button onClick={onUploadComplete}>{`UploadMock-${kind}`}</button>
  },
}))

vi.mock("@/components/assets/GuidedEvidenceForm", () => ({
  default: () => <div data-testid="manual-evidence-form">ManualEvidenceMock</div>,
}))

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock("@/components/ui/ConfirmDialog", () => ({
  default: ({ isOpen, onConfirm, onCancel, title }: { isOpen: boolean; onConfirm: () => void; onCancel: () => void; title?: string; message?: string; confirmLabel?: string; confirmVariant?: string }) => (
    <div data-testid={isOpen ? "confirm-dialog" : "confirm-dialog-closed"}>
      {isOpen ? <span>{title}</span> : null}
      {/* Always expose confirm so the early-return guard (no selected id) can be exercised. */}
      <button onClick={onConfirm}>{isOpen ? "Confirm Delete" : "Confirm Delete (no selection)"}</button>
      <button onClick={onCancel}>Cancel Delete</button>
    </div>
  ),
}))

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}))

const makeStmt = (id: string, name: string, status: BankStatement["status"], extra: Record<string, unknown> = {}): BankStatement => ({
  ...({} as BankStatement), id, original_filename: name, institution: "DBS", status, transactions: [], ...extra,
} as BankStatement)

describe("StatementsPage", () => {
  const mockedApiFetch = vi.mocked(apiOperation)

  function resolveQueued(queue: unknown[], fallback: unknown) {
    const next = queue.length ? queue.shift() : fallback
    return next instanceof Error ? Promise.reject(next) : Promise.resolve(next)
  }

  const emptyWorkflowStatus = {
    primary_state: "empty",
    next_action: { type: "upload", count: 0, href: "/upload", label: "Upload statements", summary: "Add source documents." },
    report_readiness: { state: "none", blocking_count: 0, href: "/reports" },
    event_counts: { unread: 0, action_required: 0, blocked: 0 },
  }

  function mockStatementsPageApi({
    statements,
    deletes = [],
    workflowStatus = emptyWorkflowStatus,
    workflowEvents = { total: 0, items: [], sessions: [] },
    pendingTransfers = { items: [], total: 0 },
  }: {
    statements: unknown[]
    deletes?: unknown[]
    workflowStatus?: unknown
    workflowEvents?: unknown
    pendingTransfers?: unknown
  }) {
    const statementQueue = [...statements]
    const deleteQueue = [...deletes]

    mockedApiFetch.mockImplementation((path: any, options?: any) => {
      const url = String(path)
      if (url === "/api/statements" || url === "list_statements_statements_get") {
        return resolveQueued(statementQueue, { items: [] })
      }
      if (url === "get_workflow_status_endpoint_workflow_status_get") return Promise.resolve(workflowStatus)
      if (url === "list_workflow_events_endpoint_workflow_events_get") return Promise.resolve(workflowEvents)
      if (url === "list_processing_pending_accounts_processing_pending_get") return Promise.resolve(pendingTransfers)
      if (
        url === "delete_statement_statements__statement_id__delete" ||
        (url.startsWith("/api/statements/") && options?.method === "DELETE")
      ) {
        return resolveQueued(deleteQueue, undefined)
      }
      return Promise.reject(new Error(`Unexpected api call: ${url}`))
    })
  }

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
    latestUploadComplete = null
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it("AC-extraction.fe-stage1-review.16 keeps upload polling single-flight and supersedes stale work", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const parsingResponse = { items: [makeStmt("s-poll", "parsing.pdf", "parsing")] }
    const terminalResponse = { items: [makeStmt("s-poll", "ready.pdf", "parsed")] }
    const poll = deferred<typeof parsingResponse>()
    const teardownRefresh = deferred<typeof terminalResponse>()
    let statementReads = 0
    mockedApiFetch.mockImplementation((path) => {
      const url = String(path)
      if (url === "get_workflow_status_endpoint_workflow_status_get") return Promise.resolve(emptyWorkflowStatus)
      if (url === "list_workflow_events_endpoint_workflow_events_get") return Promise.resolve({ total: 0, items: [], sessions: [] })
      if (url === "list_processing_pending_accounts_processing_pending_get") return Promise.resolve({ items: [], total: 0 })
      if (url !== "/api/statements" && url !== "list_statements_statements_get") {
        return Promise.reject(new Error(`Unexpected api call: ${url}`))
      }
      statementReads += 1
      if (statementReads === 1) return Promise.resolve(parsingResponse)
      if (statementReads === 2) return poll.promise
      if (statementReads === 3) return Promise.resolve(terminalResponse)
      return teardownRefresh.promise
    })

    const view = render(<StatementsPage />)
    await screen.findByText("AI Parsing in Progress")

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(statementReads).toBe(2)
    const statementCalls = () => mockedApiFetch.mock.calls.filter(([id]) => id === "list_statements_statements_get")
    const pollSignal = statementCalls()[1]?.[1]?.signal
    expect(pollSignal).toBeInstanceOf(AbortSignal)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })
    expect(statementReads).toBe(2)

    fireEvent.click(screen.getByText("UploadMock-statement"))
    await screen.findByText("ready.pdf")
    expect(pollSignal?.aborted).toBe(true)

    await act(async () => {
      poll.resolve(parsingResponse)
      await poll.promise
    })
    expect(screen.getByText("ready.pdf")).toBeInTheDocument()
    expect(screen.queryByText("parsing.pdf")).toBeNull()

    fireEvent.click(screen.getByText("UploadMock-statement"))
    await waitFor(() => expect(statementReads).toBe(4))
    const teardownSignal = statementCalls()[3]?.[1]?.signal
    view.unmount()
    expect(teardownSignal?.aborted).toBe(true)
    latestUploadComplete?.()
    expect(statementReads).toBe(4)

    await act(async () => {
      teardownRefresh.resolve(terminalResponse)
      await teardownRefresh.promise
      await vi.advanceTimersByTimeAsync(6000)
    })
    expect(statementReads).toBe(4)
  })

  // AC-extraction.fe-stage1-review.1
  it("AC16.14.10 AC22.1.8 renders the uploader and upload history (loading, error, empty, populated)", async () => {
    mockStatementsPageApi({
      statements: [
        new Error("load failed"),
        { items: [] },
        {
          items: [
            makeStmt("s1", "stmt.pdf", "approved", {
              period_start: "2026-01-01", period_end: "2026-01-31", currency: "SGD", confidence_score: 90,
              opening_balance: 100, closing_balance: 200, balance_validated: true, validation_error: null,
            }),
          ],
        },
      ],
    })

    render(<StatementsPage />)

    await waitFor(() => expect(screen.getAllByText("load failed")).toHaveLength(2))
    fireEvent.click(screen.getByRole("button", { name: "Retry loading statements" }))
    await waitFor(() => expect(screen.getByText("No statements uploaded yet")).toBeInTheDocument())
    fireEvent.click(screen.getByText("UploadMock-statement"))
    await waitFor(() => expect(screen.getByText("stmt.pdf")).toBeInTheDocument())
  })

  // AC-extraction.fe-remainder-extraction.2
  it("AC19.15.1 exposes exactly three intake entries: one statement uploader plus CSV and Manual", async () => {
    mockStatementsPageApi({ statements: [{ items: [] }] })

    render(<StatementsPage />)

    // One primary statement uploader — the user never pre-classifies bank vs
    // brokerage; the AI identifies the type after upload.
    await waitFor(() => expect(screen.getByText("UploadMock-statement")).toBeInTheDocument())
    // CSV is a separate entry (non-standard columns need their own mapping).
    expect(screen.getByText("CSV import")).toBeInTheDocument()
    expect(screen.getByText("UploadMock-csv")).toBeInTheDocument()
    // Manual records (ESOP/RSU, property, …) is one entry, not one card per class.
    expect(screen.getByText("Manual records")).toBeInTheDocument()
    expect(screen.getByTestId("manual-evidence-form")).toBeInTheDocument()
  })

  // AC-extraction.fe-remainder-extraction.3
  it("AC19.15.2 keeps secondary intake passive: CSV and Manual folded, no per-class checklist, no readiness fetch", async () => {
    mockStatementsPageApi({ statements: [{ items: [] }] })

    const { container } = render(<StatementsPage />)

    await waitFor(() => expect(screen.getByText("UploadMock-statement")).toBeInTheDocument())
    // CSV and Manual live in <details> that are collapsed by default — they
    // never compete with the primary statement entry for attention.
    const folded = container.querySelectorAll("details")
    expect(folded).toHaveLength(2)
    folded.forEach((node) => expect(node.hasAttribute("open")).toBe(false))
    // The retired per-source-class intake checklist must not return.
    expect(screen.queryByTestId("source-intake-bank_statement")).toBeNull()
    expect(screen.queryByTestId("source-intake-manual_record")).toBeNull()
    // The page does not pull package data merely to render intake entries.
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "list_statements_statements_get",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it("AC22.5.x surfaces a parsed statement as ready-to-review with a direct review deep-link", async () => {
    routerPushMock.mockClear()
    mockStatementsPageApi({
      statements: [
        {
          items: [
            makeStmt("s9", "ready.pdf", "parsed", {
              period_start: "2026-01-01", period_end: "2026-01-31", currency: "SGD", confidence_score: 90,
              opening_balance: 100, closing_balance: 200, balance_validated: true, validation_error: null,
            }),
          ],
        },
      ],
    })

    render(<StatementsPage />)

    await waitFor(() => expect(screen.getByText("ready.pdf")).toBeInTheDocument())
    // Plain-language status, not the raw "parsed" word.
    expect(screen.getByText("Ready to review")).toBeInTheDocument()
    expect(screen.queryByText("parsed")).toBeNull()

    // Direct deep-link into the one statement page, where the review happens.
    fireEvent.click(screen.getByRole("button", { name: /Review/i }))
    expect(routerPushMock).toHaveBeenCalledWith("/statements/s9")
  })

  it("AC22.5.x maps every status to a plain-language label (no raw 'uploaded')", async () => {
    mockStatementsPageApi({
      statements: [{ items: [makeStmt("s10", "fresh.pdf", "uploaded", { currency: "SGD" })] }],
    })

    render(<StatementsPage />)

    await waitFor(() => expect(screen.getByText("fresh.pdf")).toBeInTheDocument())
    expect(screen.getByText("Uploaded")).toBeInTheDocument()
    expect(screen.queryByText("uploaded")).toBeNull()
  })

  it("AC22.5.x labels rejected statements and falls back gracefully for unknown statuses", async () => {
    mockStatementsPageApi({
      statements: [
        {
          items: [
            makeStmt("s11", "rejected.pdf", "rejected", {
              period_start: "2026-01-01", period_end: "2026-01-31", currency: "SGD", confidence_score: 40,
              opening_balance: 0, closing_balance: 0, balance_validated: false, validation_error: "Could not read totals",
            }),
            makeStmt("s12", "weird.pdf", "frobnicating" as unknown as BankStatement["status"], {
              period_start: "2026-01-01", period_end: "2026-01-31", currency: "SGD", confidence_score: 50,
              opening_balance: 0, closing_balance: 0,
            }),
          ],
        },
      ],
    })

    render(<StatementsPage />)

    await waitFor(() => expect(screen.getByText("rejected.pdf")).toBeInTheDocument())
    expect(screen.getByText("Rejected")).toBeInTheDocument()
    // Unknown status degrades to its raw value rather than crashing.
    expect(screen.getByText("frobnicating")).toBeInTheDocument()
  })

  // AC-extraction.fe-stage1-review.2
  // AC-extraction.fe-ia-extraction.2
  it("AC16.14.11 AC22.11.1 enables polling with an honest parsing state (no fabricated progress)", async () => {
    mockStatementsPageApi({
      statements: [
        {
          items: [
            {
              id: "s2",
              original_filename: "parsing.pdf",
              institution: "DBS",
              status: "parsing",
              period_start: null,
              period_end: null,
              currency: null,
              confidence_score: null,
              transactions: [],
              opening_balance: null,
              closing_balance: null,
              balance_validated: null,
              validation_error: null,
            },
          ],
        },
      ],
    })
    const intervalSpy = vi.spyOn(globalThis, "setInterval")

    render(<StatementsPage />)

    await waitFor(() => expect(screen.getByText("AI Parsing in Progress")).toBeInTheDocument())
    expect(intervalSpy).toHaveBeenCalled()

    // AC22.11.1: the parsing state is honest — a time expectation, and NO
    // fabricated fixed-percentage progress bar.
    const status = screen.getByRole("status")
    expect(status).toHaveTextContent(/usually takes ~2–3 minutes/i)
    expect(status.querySelector('[style*="width: 60%"]')).toBeNull()
  })

  // AC-extraction.fe-stage1-review.3
  it("AC16.14.12 delete action calls delete API and toast", async () => {
    mockStatementsPageApi({
      statements: [
        {
          items: [
            makeStmt("s3", "delete.pdf", "approved", {
              period_start: "2026-01-01", period_end: "2026-01-31", currency: "SGD", confidence_score: 88,
              opening_balance: 50, closing_balance: 70, balance_validated: true, validation_error: null,
            }),
          ],
        },
        { items: [] },
      ],
      deletes: [undefined],
    })

    render(<StatementsPage />)
    await waitFor(() => expect(screen.getByText("delete.pdf")).toBeInTheDocument())
    fireEvent.click(screen.getByTitle("Delete Statement"))
    // ConfirmDialog should now be open
    await waitFor(() => expect(screen.getByTestId("confirm-dialog")).toBeInTheDocument())
    fireEvent.click(screen.getByText("Confirm Delete"))
    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "delete_statement_statements__statement_id__delete",
        { path: { statement_id: "s3" } },
      )
    })
    expect(showToastMock).toHaveBeenCalledWith("Statement deleted successfully", "success")
})

  it("AC16.28.2 AC16.28.3 exposes statement delete action with an accessible label", async () => {
    mockStatementsPageApi({
      statements: [
        {
          items: [
            makeStmt("s3", "delete.pdf", "approved", {
              period_start: "2026-01-01", period_end: "2026-01-31", currency: "SGD", confidence_score: 88,
              opening_balance: 50, closing_balance: 70, balance_validated: true, validation_error: null,
            }),
          ],
        },
      ],
    })

    render(<StatementsPage />)

    await waitFor(() => expect(screen.getByText("delete.pdf")).toBeInTheDocument())
    expect(screen.getByRole("button", { name: "Delete Statement" })).toBeInTheDocument()
  })

  it("test_AC8_13_48 renders missing statement values and surfaces delete failures", async () => {
    mockStatementsPageApi({
      statements: [
        {
          items: [
            makeStmt("s4", "needs-review.pdf", "parsed", {
              institution: "Unknown", balance_validated: false, validation_error: "Balance mismatch",
            }),
          ],
        },
      ],
      deletes: [new Error("delete failed")],
    })

    render(<StatementsPage />)

    await waitFor(() => expect(screen.getByText("needs-review.pdf")).toBeInTheDocument())
    expect(screen.getByText("Parsing...")).toBeInTheDocument()
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("Needs Review")).toBeInTheDocument()

    fireEvent.click(screen.getByTitle("Delete Statement"))
    await waitFor(() => expect(screen.getByTestId("confirm-dialog")).toBeInTheDocument())
    fireEvent.click(screen.getByText("Cancel Delete"))
    expect(screen.queryByTestId("confirm-dialog")).not.toBeInTheDocument()

    fireEvent.click(screen.getByTitle("Delete Statement"))
    fireEvent.click(screen.getByText("Confirm Delete"))

    await waitFor(() => expect(screen.getAllByText("delete failed").length).toBeGreaterThan(0))
  })

  it("test_AC8_13_49 ignores delete confirmation when no statement is selected", async () => {
    mockStatementsPageApi({ statements: [{ items: [] }] })

    render(<StatementsPage />)

    await waitFor(() => expect(screen.getByText("No statements uploaded yet")).toBeInTheDocument())

    // The dialog is closed and no statement is selected: confirming must hit the
    // early-return guard and never issue a DELETE request.
    mockedApiFetch.mockClear()
    fireEvent.click(screen.getByText("Confirm Delete (no selection)"))

    await waitFor(() => expect(screen.queryByTestId("confirm-dialog")).not.toBeInTheDocument())
    expect(mockedApiFetch).not.toHaveBeenCalled()
    expect(showToastMock).not.toHaveBeenCalled()
  })

  // AC-extraction.fe-stage1-review.18
  it("AC-extraction.fe-stage1-review.18 exposes View Report action for approved statements and Review & Approve for parsed statements", async () => {
    mockStatementsPageApi({
      statements: [
        {
          items: [
            makeStmt("s-parsed", "parsed.pdf", "parsed", {
              period_start: "2026-01-01", period_end: "2026-01-31", currency: "SGD", confidence_score: 95,
              opening_balance: 100, closing_balance: 200, balance_validated: true, validation_error: null,
            }),
            makeStmt("s-approved", "approved.pdf", "approved", {
              institution: "OCBC", period_start: "2026-01-01", period_end: "2026-01-31", currency: "SGD", confidence_score: 98,
              opening_balance: 500, closing_balance: 800, balance_validated: true, validation_error: null,
            }),
          ],
        },
      ],
    })

    render(<StatementsPage />)

    await waitFor(() => expect(screen.getByText("parsed.pdf")).toBeInTheDocument())
    expect(screen.getByRole("button", { name: "Review & Approve →" })).toBeInTheDocument()

    const viewReportSecondary = screen.getByRole("button", { name: "View Report" })
    expect(viewReportSecondary).toBeInTheDocument()
    fireEvent.click(viewReportSecondary)
    expect(routerPushMock).toHaveBeenCalledWith("/reports/balance-sheet")

    const viewReportBtn = screen.getByRole("button", { name: "View Report →" })
    expect(viewReportBtn).toBeInTheDocument()
    fireEvent.click(viewReportBtn)
    expect(routerPushMock).toHaveBeenCalledWith("/reports/balance-sheet")

    const viewTxnsBtn = screen.getByRole("button", { name: "View Transactions" })
    expect(viewTxnsBtn).toBeInTheDocument()
    fireEvent.click(viewTxnsBtn)
    expect(routerPushMock).toHaveBeenCalledWith("/statements/s-approved")

    expect(screen.getByRole("link", { name: "Open Reports →" })).toHaveAttribute(
      "href",
      "/reports/balance-sheet",
    )
    expect(screen.getByTestId("upload-processing-summary")).toHaveTextContent(
      "0 parsing · 1 parsed · 1 approved",
    )
    expect(screen.queryByRole("link", { name: "Compare with PDF" })).toBeNull()
    expect(screen.getByRole("link", { name: "parsed.pdf" })).toHaveAttribute("href", "/statements/s-parsed")
    expect(screen.getByRole("link", { name: "approved.pdf" })).toHaveAttribute("href", "/statements/s-approved")
    fireEvent.click(screen.getByRole("button", { name: "Review & Approve →" }))
    expect(routerPushMock).toHaveBeenCalledWith("/statements/s-parsed")
    expect(document.querySelector('a[href$="/review"]')).toBeNull()
  })

  it("counts active parsing jobs in place and falls back to institution period title", async () => {
    mockStatementsPageApi({
      statements: [
        {
          items: [
            makeStmt("s-fallback", "", "parsing", {
              institution: "DBS",
              period_start: "2026-02-01",
              period_end: "2026-02-28",
              currency: "SGD",
            }),
          ],
        },
      ],
    })

    render(<StatementsPage />)

    await waitFor(() =>
      expect(
        screen.getByRole("link", { name: "DBS (2026-02-01 – 2026-02-28)" }),
      ).toHaveAttribute("href", "/statements/s-fallback"),
    )
    expect(screen.getByTestId("upload-processing-summary")).toHaveTextContent(
      "1 parsing · 0 parsed · 0 approved",
    )
    expect(screen.queryByRole("link", { name: "Processing Queue →" })).toBeNull()
    expect(document.querySelector('a[href="/processing"]')).toBeNull()
  })

  // AC-extraction.fe-stage1-review.20
  it("AC-extraction.fe-stage1-review.20 shows workflow notices and in-flight transfers on the upload page", async () => {
    mockStatementsPageApi({
      statements: [{ items: [makeStmt("s1", "march.pdf", "parsed", { period_start: "2026-03-01", period_end: "2026-03-31", currency: "SGD" })] }],
      workflowStatus: {
        primary_state: "needs_action",
        next_action: { type: "review_required", count: 1, href: "/statements/s1", label: "Review required", summary: "Confirm the statement." },
        report_readiness: { state: "blocked", blocking_count: 1, href: "/reports/package" },
        event_counts: { unread: 1, action_required: 1, blocked: 0 },
      },
      workflowEvents: {
        total: 1,
        items: [{
          id: "e1", user_id: "u1", session_id: "ses1", occurred_at: "2026-03-02T00:00:00Z", family: "bank_statement.action_required",
          severity: "action_required", status: "unread", title: "March statement needs review", summary: "Low-confidence rows wait for you.",
          source_type: "bank_statement", source_id: "s1", action_href: "/statements/s1", report_impact: "blocked",
          dedupe_key: "event:e1", created_at: "2026-03-02T00:00:00Z", updated_at: "2026-03-02T00:00:00Z",
        }],
        sessions: [{
          id: "ses1", status: "active", title: "Upload-to-report session", summary: "Current work.", started_at: "2026-03-01T00:00:00Z",
          last_event_at: "2026-03-02T00:00:00Z", source_count: 1, primary_state: "needs_action",
          report_readiness: { state: "blocked", blocking_count: 1, href: "/reports/package" },
          event_counts: { unread: 1, action_required: 1, blocked: 0 },
        }],
      },
      pendingTransfers: {
        items: [{ entry_id: "t1", from_account: "DBS Savings", to_account: "OCBC Current", amount: "250.00", currency: "SGD", initiated_date: "2026-03-05", days_outstanding: 10, description: "Move to OCBC" }],
        total: 1,
      },
    })

    render(<StatementsPage />)

    expect(await screen.findByRole("heading", { name: "Workflow status" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Workflow events" })).toBeInTheDocument()
    const noticeLinks = screen.getAllByRole("link", { name: "Open March statement needs review" })
    expect(noticeLinks.length).toBeGreaterThan(0)
    for (const link of noticeLinks) expect(link).toHaveAttribute("href", "/statements/s1")
    const transfers = await screen.findByRole("region", { name: "Transfers in flight" })
    expect(transfers).toHaveTextContent("DBS Savings")
    expect(transfers).toHaveTextContent("OCBC Current")
    expect(transfers).toHaveTextContent("10d")
    expect(screen.getByText("march.pdf")).toBeInTheDocument()
    expect(document.querySelector('a[href="/notifications"], a[href="/processing"]')).toBeNull()
  })
})

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import StatementDetailPage from "@/app/(main)/statements/[id]/page"
import { apiOperation } from "@/lib/api-client"

const showToastMock = vi.fn()
const mockSearchParams = new URLSearchParams()
let mockStatementId = "s1"

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ id: mockStatementId }),
  useSearchParams: () => mockSearchParams,
}))

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}))

const parsedStatement = {
  id: "s1",
  original_filename: "statement-jan.pdf",
  institution: "DBS",
  currency: "SGD",
  period_start: "2026-01-01",
  period_end: "2026-01-31",
  opening_balance: 1000,
  closing_balance: 1500,
  confidence_score: 92,
  balance_validated: true,
  validation_error: null,
  status: "parsed",
  parsing_progress: 100,
  transactions: [
    {
      id: "t1",
      txn_date: "2026-01-02",
      description: "Salary",
      reference: "R1",
      amount: 500,
      direction: "IN",
      currency: "SGD",
      balance_after: 1500,
      confidence: "high",
      status: "matched",
    },
  ],
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe("StatementDetailPage", () => {
  const mockedApiFetch = vi.mocked(apiOperation)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
    mockStatementId = "s1"
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it("AC-extraction.fe-stage1-review.15 keeps detail polling single-flight and aborts active work on teardown", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const parsingStatement = {
      ...parsedStatement,
      status: "parsing",
      parsing_progress: 50,
    }
    const poll = deferred<typeof parsedStatement>()
    mockedApiFetch
      .mockResolvedValueOnce(parsingStatement)
      .mockImplementation(() => poll.promise)

    const view = render(<StatementDetailPage />)
    await screen.findByText(/Parsing in progress/)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(mockedApiFetch).toHaveBeenCalledTimes(2)
    const pollSignal = mockedApiFetch.mock.calls[1]?.[1]?.signal
    expect(pollSignal).toBeInstanceOf(AbortSignal)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })
    expect(mockedApiFetch).toHaveBeenCalledTimes(2)

    view.unmount()
    expect(pollSignal?.aborted).toBe(true)

    await act(async () => {
      poll.resolve(parsedStatement)
      await poll.promise
      await vi.advanceTimersByTimeAsync(6000)
    })
    expect(mockedApiFetch).toHaveBeenCalledTimes(2)
    expect(showToastMock).not.toHaveBeenCalled()
  })

  it("AC-extraction.fe-stage1-review.15 ignores the prior statement response after an id change", async () => {
    const oldRequest = deferred<typeof parsedStatement>()
    const newStatement = {
      ...parsedStatement,
      id: "s2",
      original_filename: "new-statement.pdf",
    }
    mockedApiFetch
      .mockImplementationOnce(() => oldRequest.promise)
      .mockResolvedValueOnce(newStatement)

    const view = render(<StatementDetailPage />)
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(1))
    const oldSignal = mockedApiFetch.mock.calls[0]?.[1]?.signal

    mockStatementId = "s2"
    view.rerender(<StatementDetailPage />)

    await screen.findByText("new-statement.pdf")
    expect(oldSignal?.aborted).toBe(true)

    await act(async () => {
      oldRequest.resolve(parsedStatement)
      await oldRequest.promise
    })
    expect(screen.getByText("new-statement.pdf")).toBeInTheDocument()
    expect(screen.queryByText("statement-jan.pdf")).toBeNull()
  })

  it("AC-extraction.fe-stage1-review.15 lets explicit retry refresh supersede an active poll", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const parsingStatement = { ...parsedStatement, status: "parsing", parsing_progress: 50 }
    const stalePoll = deferred<typeof parsedStatement>()
    const reparsingStatement = { ...parsedStatement, status: "parsing", parsing_progress: 10 }
    mockedApiFetch
      .mockResolvedValueOnce(parsingStatement)
      .mockRejectedValueOnce(new Error("poll 1 failed"))
      .mockRejectedValueOnce(new Error("poll 2 failed"))
      .mockRejectedValueOnce(new Error("poll 3 failed"))
      .mockImplementationOnce(() => stalePoll.promise)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(reparsingStatement)

    render(<StatementDetailPage />)
    await screen.findByText(/Parsing in progress/)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000)
    })
    await screen.findByText("Auto-refresh Stopped")

    const resumeButton = screen.getByRole("button", { name: "Resume Auto-Refresh" })
    const retryButton = screen.getByRole("button", { name: "Retry Parse" })
    await act(async () => {
      resumeButton.click()
      retryButton.click()
      await Promise.resolve()
    })

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(7))
    const staleSignal = mockedApiFetch.mock.calls[4]?.[1]?.signal
    expect(staleSignal?.aborted).toBe(true)
    expect(await screen.findByText(/Parsing in progress/)).toBeInTheDocument()

    await act(async () => {
      stalePoll.resolve(parsedStatement)
      await stalePoll.promise
    })
    expect(screen.getByText(/Parsing in progress/)).toBeInTheDocument()
  })

  const validBalance = {
    opening_balance: "1000.00", closing_balance: "1500.00", calculated_closing: "1500.00",
    opening_delta: "0.00", closing_delta: "0.00", opening_match: true, closing_match: true, validated_at: "2026-01-31T00:00:00Z",
  }

  function mockStatementApi(read: () => Record<string, unknown>, onRetry?: () => void) {
    mockedApiFetch.mockImplementation(((operationId: string) => {
      switch (operationId) {
        case "get_statement_statements__statement_id__get":
          return Promise.resolve(read())
        case "get_statement_for_review_statements__statement_id__review_get":
          return Promise.resolve({ ...read(), balance_validation_result: validBalance, source_missing_facts: [], source_envelope_reviewable: false, reviewed_envelope: null })
        case "list_pending_review_statements_pending_review_get":
          return Promise.resolve({ items: [{ id: "s1" }], total: 1 })
        case "get_review_conflicts_review_conflicts__statement_id__get":
          return Promise.resolve({ duplicates: [], transfer_pairs: [], resolved: true })
        case "retry_statement_parsing_statements__statement_id__retry_post":
          onRetry?.()
          return Promise.resolve({})
        default:
          return Promise.reject(new Error(`Unexpected operation ${operationId}`))
      }
    }) as unknown as typeof apiOperation)
  }

  // AC-extraction.fe-stage1-review.4
  it("AC16.18.1 loads detail data and renders transactions", async () => {
    mockStatementApi(() => parsedStatement)

    render(<StatementDetailPage />)

    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())
    expect(screen.getAllByText("Salary").length).toBeGreaterThan(0)
    expect(
      screen.getByTestId("statement-original-filename-badge"),
    ).toHaveTextContent("Source file: statement-jan.pdf")
    expect(screen.getByText(/Confidence 92% \(/)).toBeInTheDocument()
  })

  // AC-extraction.fe-stage1-review.19
  it("AC-extraction.fe-stage1-review.19 shows the PDF original beside the extracted transactions on one page", async () => {
    mockStatementApi(() => parsedStatement)

    render(<StatementDetailPage />)

    const workbench = await screen.findByTestId("statement-side-by-side-workbench")
    expect(within(workbench).getByRole("heading", { name: "PDF Preview" })).toBeInTheDocument()
    expect(within(workbench).getByRole("heading", { name: "Transactions" })).toBeInTheDocument()
    expect(within(workbench).getAllByText("Salary").length).toBeGreaterThan(0)
    await screen.findByRole("button", { name: "Approve" })
    expect(document.querySelector('a[href$="/review"]')).toBeNull()
    expect(screen.getByRole("link", { name: "← Back to Upload" })).toHaveAttribute("href", "/upload")
  })

  // AC-extraction.fe-stage1-review.5
  it("AC16.18.2 shows approve and reject only while the statement is parsed", async () => {
    mockStatementApi(() => parsedStatement)
    const parsed = render(<StatementDetailPage />)

    expect(await screen.findByRole("button", { name: "Approve" })).toBeEnabled()
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled()
    parsed.unmount()

    mockedApiFetch.mockReset()
    mockStatementApi(() => ({ ...parsedStatement, status: "approved" }))
    render(<StatementDetailPage />)

    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("get_statement_for_review_statements__statement_id__review_get", expect.anything()))
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument()
    expect(mockedApiFetch).not.toHaveBeenCalledWith("approve_statement_stage1_statements__statement_id__review_approve_post", expect.anything())
    expect(mockedApiFetch).not.toHaveBeenCalledWith("reject_statement_stage1_statements__statement_id__review_reject_post", expect.anything())
  })

  // AC-extraction.fe-stage1-review.6
  it("AC16.18.3 retry parse posts retry API and refreshes", async () => {
    let current: Record<string, unknown> = { ...parsedStatement, status: "rejected", validation_error: "parse failed" }
    const retried = vi.fn()
    mockStatementApi(() => current, () => {
      retried()
      current = parsedStatement
    })

    render(<StatementDetailPage />)

    await waitFor(() => expect(screen.getByText("Parsing Failed")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Retry Parse" }))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "retry_statement_parsing_statements__statement_id__retry_post",
        {
          path: { statement_id: "s1" },
        },
      ),
    )
    expect(retried).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(screen.queryByText("Parsing Failed")).not.toBeInTheDocument())
  })

  it("shows not found state", async () => {
    mockedApiFetch.mockResolvedValueOnce(null)
    render(<StatementDetailPage />)
    await waitFor(() => expect(screen.getByText("Statement not found")).toBeInTheDocument())
  })

  it("stops polling after consecutive errors", async () => {
    const parsingState = { ...parsedStatement, status: "parsing", parsing_progress: 50 }
    mockedApiFetch.mockResolvedValueOnce(parsingState)
    mockedApiFetch.mockRejectedValue(new Error("Poll Failure"))
    render(<StatementDetailPage />)
    await waitFor(() => expect(screen.getByText(/Parsing in progress/)).toBeInTheDocument(), { timeout: 3000 })
    await waitFor(() => expect(screen.getByText(/Auto-refresh Stopped/)).toBeInTheDocument(), { timeout: 15000 })
  }, 20000)
})

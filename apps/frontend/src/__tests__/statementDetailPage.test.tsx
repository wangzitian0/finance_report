import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import StatementDetailPage from "@/app/(main)/statements/[id]/page"
import { apiFetch } from "@/lib/api"

const showToastMock = vi.fn()
const mockSearchParams = new URLSearchParams()
let mockStatementId = "s1"

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: mockStatementId }),
  useSearchParams: () => mockSearchParams,
}))

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
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
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
    mockSearchParams.delete("approved")
    mockSearchParams.delete("entriesCreated")
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

  // AC-extraction.fe-stage1-review.4
  it("AC16.18.1 loads detail data and renders transactions", async () => {
    mockedApiFetch.mockResolvedValueOnce(parsedStatement)

    render(<StatementDetailPage />)

    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())
    expect(screen.getByText("Salary")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Start Review →" })).toHaveAttribute("href", "/statements/s1/review")
  })

  // AC-extraction.fe-stage1-review.5
  it("AC16.18.2 detail page is read-only for approval actions", async () => {
    mockedApiFetch.mockResolvedValueOnce(parsedStatement)

    render(<StatementDetailPage />)

    await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument())

    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument()
    expect(mockedApiFetch).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/statements/s1/approve"),
      expect.anything(),
    )
    expect(mockedApiFetch).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/statements/s1/reject"),
      expect.anything(),
    )
  })

  // AC-extraction.fe-stage1-review.6
  it("AC16.18.3 retry parse posts retry API and refreshes", async () => {
    const rejectedStatement = { ...parsedStatement, status: "rejected", validation_error: "parse failed" }
    mockedApiFetch.mockResolvedValueOnce(rejectedStatement).mockResolvedValueOnce(undefined).mockResolvedValueOnce(parsedStatement)

    render(<StatementDetailPage />)

    await waitFor(() => expect(screen.getByText("Parsing Failed")).toBeInTheDocument())
    fireEvent.click(screen.getAllByRole("button", { name: "Retry Parse" })[0])

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/s1/retry", {
        method: "POST",
      }),
    )
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

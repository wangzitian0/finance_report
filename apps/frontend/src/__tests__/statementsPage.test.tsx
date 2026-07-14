import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import StatementsPage from "@/app/(main)/upload/page"
import { apiFetch } from "@/lib/api"
import type { BankStatement, PersonalReportPackageReadinessResponse } from "@/lib/types"

const showToastMock = vi.fn()

const DEFAULT_READINESS: PersonalReportPackageReadinessResponse = {
  package_id: "personal-financial-report-package",
  state: "ready",
  label: "Ready",
  action_href: "/reports/package",
  blocking_count: 0,
  blockers: [],
  source_summary: {},
  source_trust_summary: {
    source_classes: ["bank_statement"],
    deterministic_pr_source_classes: ["bank_statement"],
    post_merge_llm_ocr_source_classes: ["bank_statement"],
    manual_trusted_source_classes: [],
    gap_source_classes: [],
    blocker_codes: [],
  },
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
  default: ({ onUploadComplete, kind = "all" }: { onUploadComplete: () => void; kind?: string }) => (
    <button onClick={onUploadComplete}>{`UploadMock-${kind}`}</button>
  ),
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

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

describe("StatementsPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  function resolveQueued(queue: unknown[], fallback: unknown) {
    const next = queue.length ? queue.shift() : fallback
    return next instanceof Error ? Promise.reject(next) : Promise.resolve(next)
  }

  function mockStatementsPageApi({
    statements,
    readiness = DEFAULT_READINESS,
    deletes = [],
  }: {
    statements: unknown[]
    readiness?: unknown
    deletes?: unknown[]
  }) {
    const statementQueue = [...statements]
    const deleteQueue = [...deletes]

    mockedApiFetch.mockImplementation((path, options) => {
      const url = String(path)
      if (url.startsWith("/api/reports/package/readiness")) {
        return resolveQueued([readiness], DEFAULT_READINESS)
      }
      if (url === "/api/statements") {
        return resolveQueued(statementQueue, { items: [] })
      }
      if (url.startsWith("/api/statements/") && options?.method === "DELETE") {
        return resolveQueued(deleteQueue, undefined)
      }
      return Promise.reject(new Error(`Unexpected apiFetch call: ${url}`))
    })
  }

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  // AC-extraction.fe-stage1-review.1
  it("AC16.14.10 AC22.1.8 renders the uploader and upload history (loading, error, empty, populated)", async () => {
    mockStatementsPageApi({
      statements: [
        new Error("load failed"),
        { items: [] },
        {
        items: [
          {
            id: "s1",
            original_filename: "stmt.pdf",
            institution: "DBS",
            status: "approved",
            period_start: "2026-01-01",
            period_end: "2026-01-31",
            currency: "SGD",
            confidence_score: 90,
            transactions: [],
            opening_balance: 100,
            closing_balance: 200,
            balance_validated: true,
            validation_error: null,
          },
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
    // The page no longer pulls report readiness just to render intake entries.
    expect(mockedApiFetch).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/reports/package/readiness"),
      expect.anything(),
    )
  })

  it("AC22.5.x surfaces a parsed statement as ready-to-review with a direct review deep-link", async () => {
    routerPushMock.mockClear()
    mockStatementsPageApi({
      statements: [
        {
          items: [
            {
              id: "s9",
              original_filename: "ready.pdf",
              institution: "DBS",
              status: "parsed",
              period_start: "2026-01-01",
              period_end: "2026-01-31",
              currency: "SGD",
              confidence_score: 90,
              transactions: [],
              opening_balance: 100,
              closing_balance: 200,
              balance_validated: true,
              validation_error: null,
            },
          ],
        },
      ],
    })

    render(<StatementsPage />)

    await waitFor(() => expect(screen.getByText("ready.pdf")).toBeInTheDocument())
    // Plain-language status, not the raw "parsed" word.
    expect(screen.getByText("Ready to review")).toBeInTheDocument()
    expect(screen.queryByText("parsed")).toBeNull()

    // Direct deep-link into the review page, skipping the detail-page hop.
    fireEvent.click(screen.getByRole("button", { name: /Review/i }))
    expect(routerPushMock).toHaveBeenCalledWith("/statements/s9/review")
  })

  it("AC22.5.x maps every status to a plain-language label (no raw 'uploaded')", async () => {
    mockStatementsPageApi({
      statements: [
        {
          items: [
            {
              id: "s10",
              original_filename: "fresh.pdf",
              institution: "DBS",
              status: "uploaded",
              period_start: null,
              period_end: null,
              currency: "SGD",
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
            {
              id: "s11",
              original_filename: "rejected.pdf",
              institution: "DBS",
              status: "rejected",
              period_start: "2026-01-01",
              period_end: "2026-01-31",
              currency: "SGD",
              confidence_score: 40,
              transactions: [],
              opening_balance: 0,
              closing_balance: 0,
              balance_validated: false,
              validation_error: "Could not read totals",
            },
            {
              id: "s12",
              original_filename: "weird.pdf",
              institution: "DBS",
              // Defensive: a status outside the known union still renders, unstyled.
              status: "frobnicating" as unknown as BankStatement["status"],
              period_start: "2026-01-01",
              period_end: "2026-01-31",
              currency: "SGD",
              confidence_score: 50,
              transactions: [],
              opening_balance: 0,
              closing_balance: 0,
              balance_validated: null,
              validation_error: null,
            },
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
            {
              id: "s3",
              original_filename: "delete.pdf",
              institution: "DBS",
              status: "approved",
              period_start: "2026-01-01",
              period_end: "2026-01-31",
              currency: "SGD",
              confidence_score: 88,
              transactions: [],
              opening_balance: 50,
              closing_balance: 70,
              balance_validated: true,
              validation_error: null,
            },
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
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/statements/s3", { method: "DELETE" })
    })
    expect(showToastMock).toHaveBeenCalledWith("Statement deleted successfully", "success")
})

  it("AC16.28.2 AC16.28.3 exposes statement delete action with an accessible label", async () => {
    mockStatementsPageApi({
      statements: [
        {
          items: [
            {
              id: "s3",
              original_filename: "delete.pdf",
              institution: "DBS",
              status: "approved",
              period_start: "2026-01-01",
              period_end: "2026-01-31",
              currency: "SGD",
              confidence_score: 88,
              transactions: [],
              opening_balance: 50,
              closing_balance: 70,
              balance_validated: true,
              validation_error: null,
            },
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
            {
              id: "s4",
              original_filename: "needs-review.pdf",
              institution: "Unknown",
              status: "parsed",
              period_start: null,
              period_end: null,
              currency: null,
              confidence_score: null,
              transactions: [],
              opening_balance: null,
              closing_balance: undefined,
              balance_validated: false,
              validation_error: "Balance mismatch",
            },
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

})

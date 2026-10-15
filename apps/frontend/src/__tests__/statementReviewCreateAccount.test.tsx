import { beforeEach, describe, expect, it, vi } from "vitest"
import { act, fireEvent, screen, waitFor } from "@testing-library/react"

import StatementReviewPage from "@/app/(main)/statements/[id]/review/page"
import { apiOperation, apiOperationDownload } from "@/lib/api-client"
import { renderReviewComponent } from "./helpers/renderReviewComponent"

vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn(), apiOperationDownload: vi.fn() }))
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ replace: vi.fn(), push: vi.fn() })),
  useSearchParams: vi.fn(() => ({ get: () => null })),
  usePathname: vi.fn(() => "/"),
  useParams: vi.fn(() => ({ id: "s1" })),
}))

const mockedApi = vi.mocked(apiOperation)
const mockedDownload = vi.mocked(apiOperationDownload)

const statement = {
  id: "s1",
  original_filename: "export.csv",
  institution: "Bank",
  currency: "SGD",
  period_start: "2026-10-01",
  period_end: "2026-10-31",
  opening_balance: "10000.00",
  closing_balance: "13500.00",
  status: "pending",
  stage1_status: null,
  account_id: null,
  balance_validation_result: { opening_match: true, closing_match: true, calculated_closing: "13500.00" },
  pdf_url: null,
  transactions: [],
  source_envelope_reviewable: true,
  source_missing_facts: [],
  source_result_digest: "digest-1",
  reviewed_envelope: null,
}

const createdAccount = { id: "acc-1", name: "Bank account", currency: "SGD" }

// A new user has no asset account. The list stays empty until the account is created.
function mockApi(create: () => Promise<unknown>) {
  let created = false
  mockedApi.mockImplementation((operationId: unknown) => {
    switch (operationId) {
      case "get_statement_for_review_statements__statement_id__review_get":
        return Promise.resolve(statement)
      case "list_pending_review_statements_pending_review_get":
        return Promise.resolve({ items: [{ id: "s1" }] })
      case "get_review_conflicts_review_conflicts__statement_id__get":
        return Promise.resolve({ duplicates: [], transfer_pairs: [] })
      case "list_accounts_accounts_get":
        return Promise.resolve({ items: created ? [createdAccount] : [] })
      case "create_account_accounts_post":
        return create().then((account) => {
          created = true
          return account
        })
      default:
        return Promise.reject(new Error(`Unexpected operation ${String(operationId)}`))
    }
  })
}

describe("Statement review: inline account creation for a new user (#2477)", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedDownload.mockResolvedValue({ blob: new Blob(["x"]), filename: "export.csv" })
    URL.createObjectURL = vi.fn(() => "blob:preview-1")
    URL.revokeObjectURL = vi.fn()
  })

  it("AC-extraction.2477.1 creates the asset account in the statement currency and selects it", async () => {
    mockApi(() => Promise.resolve(createdAccount))
    renderReviewComponent(<StatementReviewPage />)

    const button = await screen.findByRole("button", { name: "Create account" })
    // Let React run the effect that hands the latest draft to the mutation before the click.
    await act(async () => {})
    fireEvent.click(button)

    expect(await screen.findByText('Account "Bank account" created and selected.')).toBeInTheDocument()
    const creates = mockedApi.mock.calls.filter(([operationId]) => operationId === "create_account_accounts_post")
    expect(creates).toHaveLength(1)
    expect(creates[0][1]).toEqual({ body: { name: "Bank account", type: "ASSET", currency: "SGD" } })
    await waitFor(() => {
      const select = document.getElementById("custody-account") as HTMLSelectElement
      expect(select.value).toBe("acc-1")
    })
  })

  it("AC-extraction.2477.1 shows the reason when the account cannot be created", async () => {
    mockApi(() => Promise.reject(new Error("Account name already exists")))
    renderReviewComponent(<StatementReviewPage />)

    const button = await screen.findByRole("button", { name: "Create account" })
    await act(async () => {})
    fireEvent.click(button)

    expect(await screen.findByText("Account name already exists")).toBeInTheDocument()
    const select = document.getElementById("custody-account") as HTMLSelectElement
    expect(select.value).toBe("")
  })
})

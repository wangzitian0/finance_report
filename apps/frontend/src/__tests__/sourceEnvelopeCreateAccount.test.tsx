import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import {
  SourceEnvelopeConfirmation,
  type EnvelopeDraft,
} from "@/components/review/TransactionTable"

const draft: EnvelopeDraft = {
  accountId: "",
  currency: "SGD",
  periodStart: "2026-10-01",
  periodEnd: "2026-10-31",
  openingBalance: "10000.00",
  closingBalance: "13500.00",
  rationale: "",
}

function renderEnvelope(props: Partial<Parameters<typeof SourceEnvelopeConfirmation>[0]> = {}) {
  return render(
    <SourceEnvelopeConfirmation
      requiresEnvelopeConfirmation
      requiresOtherSourceReview={false}
      sourceMissingFacts={[]}
      missingFactLabels={{}}
      envelopeDraft={draft}
      onDraftChange={() => {}}
      custodyAccounts={[]}
      onConfirm={() => {}}
      isPending={false}
      {...props}
    />,
  )
}

describe("SourceEnvelopeConfirmation inline account creation (#2477)", () => {
  it("AC-extraction.2477.1 offers to create an asset account when the user has none", () => {
    const onCreateAccount = vi.fn()
    renderEnvelope({ onCreateAccount, defaultAccountName: "DBS account" })

    const name = screen.getByLabelText("New account name") as HTMLInputElement
    expect(name.value).toBe("DBS account")
    fireEvent.change(name, { target: { value: "DBS Savings" } })
    fireEvent.click(screen.getByRole("button", { name: "Create account" }))

    expect(onCreateAccount).toHaveBeenCalledWith("DBS Savings")
  })

  it("AC-extraction.2477.1 hides the create action when an asset account exists", () => {
    renderEnvelope({
      onCreateAccount: vi.fn(),
      custodyAccounts: [{ id: "a1", name: "DBS Savings", currency: "SGD" }],
    })
    expect(screen.queryByRole("button", { name: "Create account" })).toBeNull()
  })

  it("AC-extraction.2477.1 disables create without a name", () => {
    const onCreateAccount = vi.fn()
    renderEnvelope({ onCreateAccount })
    const button = screen.getByRole("button", { name: "Create account" }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    fireEvent.click(button)
    expect(onCreateAccount).not.toHaveBeenCalled()
  })

  it.each([
    { label: "Custody account", key: "accountId" as const, value: "a1" },
    { label: "Statement currency", key: "currency" as const, value: "USD" },
    { label: "Period start", key: "periodStart" as const, value: "2026-09-01" },
    { label: "Period end", key: "periodEnd" as const, value: "2026-09-30" },
    { label: "Opening balance", key: "openingBalance" as const, value: "1.00" },
    { label: "Closing balance", key: "closingBalance" as const, value: "2.00" },
    { label: "Why are these facts confirmed\\?", key: "rationale" as const, value: "Checked against the PDF" },
  ])("AC-extraction.2477.1 $label writes only the $key of the draft", ({ label, key, value }) => {
    const results: EnvelopeDraft[] = []
    renderEnvelope({
      custodyAccounts: [{ id: "a1", name: "DBS Savings", currency: "SGD" }],
      onDraftChange: (updater) => results.push(updater(draft)),
    })
    fireEvent.change(screen.getByLabelText(new RegExp(`^${label}`)), { target: { value } })
    expect(results).toEqual([{ ...draft, [key]: value }])
  })
})

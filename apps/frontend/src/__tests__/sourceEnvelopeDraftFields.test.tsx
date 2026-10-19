import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import {
  SourceEnvelopeConfirmation,
  type EnvelopeDraft,
} from "@/components/review/SourceEnvelopeConfirmation"

const draft: EnvelopeDraft = {
  accountId: "",
  currency: "SGD",
  periodStart: "2026-10-01",
  periodEnd: "2026-10-31",
  openingBalance: "10000.00",
  closingBalance: "13500.00",
  rationale: "",
}

function renderEnvelope(
  onDraftChange: (updater: (prev: EnvelopeDraft) => EnvelopeDraft) => void,
) {
  return render(
    <SourceEnvelopeConfirmation
      requiresEnvelopeConfirmation
      requiresOtherSourceReview={false}
      sourceMissingFacts={[]}
      missingFactLabels={{}}
      envelopeDraft={draft}
      onDraftChange={onDraftChange}
      custodyAccounts={[{ id: "a1", name: "DBS Savings", currency: "SGD" }]}
      onConfirm={() => {}}
      isPending={false}
    />,
  )
}

// Each field of the source envelope writes its own key of the draft and keeps the others.
const FIELDS: Array<{ label: string; key: keyof EnvelopeDraft; value: string }> = [
  { label: "Custody account", key: "accountId", value: "a1" },
  { label: "Statement currency", key: "currency", value: "USD" },
  { label: "Period start", key: "periodStart", value: "2026-09-01" },
  { label: "Period end", key: "periodEnd", value: "2026-09-30" },
  { label: "Opening balance", key: "openingBalance", value: "1.00" },
  { label: "Closing balance", key: "closingBalance", value: "2.00" },
  { label: "Why are these facts confirmed\\?", key: "rationale", value: "Checked against the PDF" },
]

describe("SourceEnvelopeConfirmation draft fields (AC-extraction.2477.1)", () => {
  it.each(FIELDS)("AC-extraction.2477.1 $label writes only the $key of the draft", ({ label, key, value }) => {
    // Apply the updater inside the handler, while the event still holds the typed value.
    const results: EnvelopeDraft[] = []
    renderEnvelope((updater) => results.push(updater(draft)))

    // The label text also holds the text of its options, so match the start of it.
    fireEvent.change(screen.getByLabelText(new RegExp(`^${label}`)), { target: { value } })

    expect(results).toEqual([{ ...draft, [key]: value }])
  })
})

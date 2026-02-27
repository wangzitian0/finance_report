import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import ReconciliationPage from "@/app/(main)/reconciliation/page"
import UnmatchedPage from "@/app/(main)/reconciliation/unmatched/page"

vi.mock("@/components/reconciliation/Workbench", () => ({
  default: () => <div>Mock Workbench</div>,
}))

vi.mock("@/components/reconciliation/UnmatchedBoard", () => ({
  default: () => <div>Mock Unmatched Board</div>,
}))

describe("Reconciliation entry pages", () => {
  it("AC16.16.4 renders workbench in reconciliation page", () => {
    render(<ReconciliationPage />)
    expect(screen.getByText("Mock Workbench")).toBeInTheDocument()
  })

  it("AC16.16.4 renders unmatched board in unmatched page", () => {
    render(<UnmatchedPage />)
    expect(screen.getByText("Mock Unmatched Board")).toBeInTheDocument()
  })
})

import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import { WorkflowInbox } from "@/components/workflow/WorkflowNotifications"
import type { WorkflowEventResponse } from "@/lib/types"

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

function event(overrides: Partial<WorkflowEventResponse>): WorkflowEventResponse {
  return {
    id: "evt",
    user_id: "u1",
    session_id: "s1",
    occurred_at: "2026-06-04T08:00:00Z",
    family: "review.required",
    severity: "action_required",
    status: "unread",
    title: "Source review required",
    summary: "statement.pdf needs source review.",
    source_type: "bank_statement",
    source_id: "stmt-1",
    action_href: "/statements/stmt-1/review",
    report_impact: "blocked",
    ...overrides,
  } as WorkflowEventResponse
}

describe("Unified notification inbox (EPIC-022 AC22.2)", () => {
  // AC-platform.fe-ia-inbox.1
  it("AC22.2.1 surfaces Stage 1 review and Stage 2 reconciliation attention with deep links", () => {
    const events: WorkflowEventResponse[] = [
      event({ id: "review", action_href: "/statements/stmt-1/review", title: "Source review required" }),
      event({
        id: "recon",
        family: "reconciliation.blocked",
        severity: "blocked",
        title: "Reconciliation review required",
        summary: "Pending matches need review before reports are ready.",
        source_type: "reconciliation",
        source_id: "run-1",
        action_href: "/reconciliation/review-queue",
      }),
    ]

    render(<WorkflowInbox events={events} sessions={[]} />)

    const stage1 = screen.getByRole("link", { name: /Open Source review required/i })
    expect(stage1).toHaveAttribute("href", "/statements/stmt-1/review")

    const stage2 = screen.getByRole("link", { name: /Open Reconciliation review required/i })
    expect(stage2).toHaveAttribute("href", "/reconciliation/review-queue")
  })

  it("AC22.2.1 shows a no-action empty state with no review queue page to visit", () => {
    render(<WorkflowInbox events={[]} sessions={[]} />)
    expect(screen.getByText("No action required")).toBeInTheDocument()
    // The empty state points at upload, not a standalone review queue.
    expect(screen.getByRole("link", { name: /Upload statements/i })).toHaveAttribute("href", "/upload")
  })
})

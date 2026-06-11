import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import NotificationsPage from "@/app/(main)/notifications/page"

vi.mock("@/components/workflow/WorkflowNotifications", () => ({
  WorkflowEventsPageContent: () => <div>Workflow events page content</div>,
}))

describe("NotificationsPage", () => {
  it("AC22.1.5 renders the workflow event center surface at /notifications", () => {
    render(<NotificationsPage />)
    expect(screen.getByText("Workflow events page content")).toBeInTheDocument()
  })
})

import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import EventsPage from "@/app/(main)/events/page"

vi.mock("@/components/workflow/WorkflowNotifications", () => ({
  WorkflowEventsPageContent: () => <div>Workflow events page content</div>,
}))

describe("EventsPage", () => {
  it("AC19.3.5 renders the workflow events content surface", () => {
    render(<EventsPage />)
    expect(screen.getByText("Workflow events page content")).toBeInTheDocument()
  })
})

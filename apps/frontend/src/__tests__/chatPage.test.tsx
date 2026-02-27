import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import ChatPage from "@/app/(main)/chat/page"

vi.mock("@/components/ChatPageClient", () => ({
  default: () => <div>Advisor Client</div>,
}))

describe("ChatPage", () => {
  it("AC16.16.3 renders advisor client", () => {
    render(<ChatPage />)
    expect(screen.getByText("Advisor Client")).toBeInTheDocument()
  })
})

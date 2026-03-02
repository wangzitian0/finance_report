import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import ChatWidget from "@/components/ChatWidget"

const pushMock = vi.fn()
let pathnameMock = "/dashboard"

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => pathnameMock,
}))

vi.mock("@/components/ChatPanel", () => ({
  __esModule: true,
  default: ({ variant, onClose }: { variant: string; onClose?: () => void }) => (
    <div data-testid="chat-panel" data-variant={variant}>
      {onClose && (
        <button type="button" onClick={onClose} data-testid="close-btn">
          Close
        </button>
      )}
    </div>
  ),
}))

describe("ChatWidget", () => {
  beforeEach(() => {
    pushMock.mockReset()
    pathnameMock = "/dashboard"
  })

  it("AC16.20.1 renders button on non-chat pages", () => {
    render(<ChatWidget />)

    expect(screen.getByRole("button", { name: /ask ai/i })).toBeInTheDocument()
    expect(screen.queryByTestId("chat-panel")).not.toBeInTheDocument()
  })

  it("AC16.20.1 returns null on /chat page", () => {
    pathnameMock = "/chat"
    const { container } = render(<ChatWidget />)

    expect(container.firstChild).toBeNull()
    expect(screen.queryByRole("button", { name: /ask ai/i })).not.toBeInTheDocument()
  })

  it("AC16.20.1 toggles chat panel on button click", async () => {
    render(<ChatWidget />)

    const button = screen.getByRole("button", { name: /ask ai/i })
    fireEvent.click(button)

    await waitFor(() => expect(screen.getByTestId("chat-panel")).toBeInTheDocument())
    expect(screen.getByTestId("chat-panel")).toHaveAttribute("data-variant", "widget")
  })

  it("AC16.20.1 closes panel via onClose callback", async () => {
    render(<ChatWidget />)

    const button = screen.getByRole("button", { name: /ask ai/i })
    fireEvent.click(button)

    await waitFor(() => expect(screen.getByTestId("chat-panel")).toBeInTheDocument())

    const closeBtn = screen.getByTestId("close-btn")
    fireEvent.click(closeBtn)

    await waitFor(() => expect(screen.queryByTestId("chat-panel")).not.toBeInTheDocument())
  })

  it("AC16.20.1 toggles panel visibility correctly", async () => {
    render(<ChatWidget />)

    const button = screen.getByRole("button", { name: /ask ai/i })

    fireEvent.click(button)
    await waitFor(() => expect(screen.getByTestId("chat-panel")).toBeInTheDocument())

    fireEvent.click(button)
    await waitFor(() => expect(screen.queryByTestId("chat-panel")).not.toBeInTheDocument())

    fireEvent.click(button)
    await waitFor(() => expect(screen.getByTestId("chat-panel")).toBeInTheDocument())
  })
})

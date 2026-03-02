import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import ChatPageClient from "@/components/ChatPageClient"

const pushMock = vi.fn()
const getMock = vi.fn()
const setMock = vi.fn()

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => ({ get: getMock }),
}))

vi.mock("next/link", () => ({
  __esModule: true,
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}))

vi.mock("@/components/ChatPanel", () => ({
  __esModule: true,
  default: ({ variant, initialPrompt }: { variant: string; initialPrompt?: string | null }) => (
    <div data-testid="chat-panel" data-variant={variant} data-prompt={initialPrompt ?? ""}>
      Chat Panel
    </div>
  ),
}))

describe("ChatPageClient", () => {
  beforeEach(() => {
    pushMock.mockReset()
    getMock.mockReset()
    setMock.mockReset()

    const storage = new Map<string, string>()
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        setMock(key, value)
        storage.set(key, value)
      },
      removeItem: (key: string) => storage.delete(key),
      clear: () => storage.clear(),
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("AC16.20.2 renders page with title and description", () => {
    getMock.mockReturnValue(null)
    render(<ChatPageClient />)

    expect(screen.getByText("AI Financial Advisor")).toBeInTheDocument()
    expect(screen.getByText(/Ask about spending trends/)).toBeInTheDocument()
  })

  it("AC16.20.2 renders navigation links", () => {
    getMock.mockReturnValue(null)
    render(<ChatPageClient />)

    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/dashboard")
    expect(screen.getByRole("link", { name: "Reports" })).toHaveAttribute("href", "/reports/balance-sheet")
  })

  it("AC16.20.2 renders ChatPanel with page variant", () => {
    getMock.mockReturnValue(null)
    render(<ChatPageClient />)

    expect(screen.getByTestId("chat-panel")).toBeInTheDocument()
    expect(screen.getByTestId("chat-panel")).toHaveAttribute("data-variant", "page")
  })

  it("AC16.20.2 passes initialPrompt to ChatPanel", () => {
    getMock.mockReturnValue("Analyze my spending")
    render(<ChatPageClient />)

    expect(screen.getByTestId("chat-panel")).toHaveAttribute("data-prompt", "Analyze my spending")
  })

  it("AC16.20.2 shows consent modal when not accepted", () => {
    getMock.mockReturnValue(null)
    render(<ChatPageClient />)

    expect(screen.getByText("Disclaimer")).toBeInTheDocument()
    expect(screen.getByText(/This AI financial advisor provides guidance/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "I understand" })).toBeInTheDocument()
  })

  it("AC16.20.2 hides consent modal after acceptance", async () => {
    getMock.mockReturnValue(null)
    render(<ChatPageClient />)

    const acceptBtn = screen.getByRole("button", { name: "I understand" })
    fireEvent.click(acceptBtn)

    await waitFor(() => expect(screen.queryByText("Disclaimer")).not.toBeInTheDocument())
    expect(setMock).toHaveBeenCalledWith("ai_advisor_disclaimer_v1", "accepted")
  })

  it("AC16.20.2 skips consent modal if already accepted", async () => {
    const storage = new Map<string, string>([["ai_advisor_disclaimer_v1", "accepted"]])
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
      clear: () => storage.clear(),
    })

    getMock.mockReturnValue(null)
    render(<ChatPageClient />)

    await waitFor(() => expect(screen.queryByText("Disclaimer")).not.toBeInTheDocument())
  })
})



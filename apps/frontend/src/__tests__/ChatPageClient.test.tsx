import type { ReactNode } from "react"
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
  default: ({ href, children, className }: { href: string; children: ReactNode; className?: string }) => (
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

function createLocalStorageStub(
  onSetItem?: (key: string, value: string) => void,
  initialData?: Record<string, string>,
) {
  const storage = new Map<string, string>(initialData ? Object.entries(initialData) : [])

  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => {
      if (onSetItem) {
        onSetItem(key, value)
      }
      storage.set(key, value)
    },
    removeItem: (key: string) => storage.delete(key),
    clear: () => storage.clear(),
  })

  return storage
}

describe("ChatPageClient", () => {
  beforeEach(() => {
    pushMock.mockReset()
    getMock.mockReset()
    setMock.mockReset()

    createLocalStorageStub((key, value) => {
      setMock(key, value)
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
    vi.unstubAllGlobals()
    createLocalStorageStub(undefined, { ai_advisor_disclaimer_v1: "accepted" })

    getMock.mockReturnValue(null)
    render(<ChatPageClient />)

    await waitFor(() => expect(screen.queryByText("Disclaimer")).not.toBeInTheDocument())
  })

  it("AC16.20.2 focus trap cycles Tab forward inside consent dialog", async () => {
    getMock.mockReturnValue(null)
    const { container } = render(<ChatPageClient />)

    // Consent dialog should be visible
    expect(screen.getByText("Disclaimer")).toBeInTheDocument()

    // The dialog wrapper div with the ref
    const dialogInner = container.querySelector(".card.animate-slide-up") as HTMLElement
    expect(dialogInner).toBeTruthy()

    // Get focusable elements inside the dialog
    const focusables = dialogInner.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )
    expect(focusables.length).toBeGreaterThan(0)

    const lastEl = focusables[focusables.length - 1]
    const firstEl = focusables[0]

    // Focus the last element and press Tab (no shift) — should wrap to first
    lastEl.focus()
    fireEvent.keyDown(dialogInner, { key: "Tab", shiftKey: false })

    // Focus the first element and press Shift+Tab — should wrap to last
    firstEl.focus()
    fireEvent.keyDown(dialogInner, { key: "Tab", shiftKey: true })

    // Press a non-Tab key — should be ignored by the trap
    fireEvent.keyDown(dialogInner, { key: "Escape" })
  })
})

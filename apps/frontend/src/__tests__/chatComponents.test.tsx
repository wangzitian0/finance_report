import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import ChatPageClient from "@/components/ChatPageClient"
import ChatWidget from "@/components/ChatWidget"

let pathnameMock = "/dashboard"

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: (key: string) => (key === "prompt" ? "cash flow" : null) }),
  usePathname: () => pathnameMock,
}))

vi.mock("@/components/ChatPanel", () => ({
  default: ({ variant, initialPrompt, onClose }: { variant: string; initialPrompt?: string | null; onClose?: () => void }) => (
    <div>
      <span>{variant}</span>
      <span>{initialPrompt || "no-prompt"}</span>
      {onClose ? <button onClick={onClose}>Close Chat</button> : null}
    </div>
  ),
}))

describe("Chat components", () => {
  beforeEach(() => {
    const storage = new Map<string, string>()
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value)
      },
      removeItem: (key: string) => {
        storage.delete(key)
      },
      clear: () => {
        storage.clear()
      },
    })
    pathnameMock = "/dashboard"
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("AC16.19.5 enforces disclaimer consent and passes initial prompt", async () => {
    render(<ChatPageClient />)

    expect(screen.getByText("Disclaimer")).toBeInTheDocument()
    expect(screen.getByText("cash flow")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "I understand" }))

    await waitFor(() => expect(screen.queryByText("Disclaimer")).toBeNull())
    expect(localStorage.getItem("ai_advisor_disclaimer_v1")).toBe("accepted")
  })

  it("AC16.19.6 hides widget on chat route and toggles elsewhere", async () => {
    pathnameMock = "/chat"
    const { rerender } = render(<ChatWidget />)
    expect(screen.queryByText("Ask AI")).toBeNull()

    pathnameMock = "/dashboard"
    rerender(<ChatWidget />)

    fireEvent.click(screen.getByRole("button", { name: /ask ai/i }))
    expect(screen.getByText("widget")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Close Chat" }))
    await waitFor(() => expect(screen.queryByText("widget")).toBeNull())
  })
})

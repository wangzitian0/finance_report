import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { ToastProvider, useToast } from "@/components/ui/Toast"

function TestToastConsumer() {
  const { showToast } = useToast()
  return (
    <div>
      <button onClick={() => showToast("saved", "success")}>Show Success</button>
      <button onClick={() => showToast("failed", "error")}>Show Error</button>
    </div>
  )
}

describe("ToastProvider component", () => {
  it("AC16.19.9 shows and dismisses notifications", () => {
    render(
      <ToastProvider>
        <TestToastConsumer />
      </ToastProvider>,
    )

    fireEvent.click(screen.getByRole("button", { name: "Show Success" }))
    expect(screen.getByText("saved")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Dismiss notification" }))
    expect(screen.queryByText("saved")).toBeNull()
  })

  it("AC16.30.4 exposes live notification semantics and supports keyboard dismissal", async () => {
    const user = userEvent.setup()

    render(
      <ToastProvider>
        <TestToastConsumer />
      </ToastProvider>,
    )

    await user.click(screen.getByRole("button", { name: "Show Error" }))

    expect(screen.getByRole("region", { name: "Notifications" })).toHaveAttribute("aria-live", "polite")
    expect(screen.getByRole("alert")).toHaveTextContent("failed")

    const dismissButton = screen.getByRole("button", { name: "Dismiss notification" })
    dismissButton.focus()
    await user.keyboard("{Enter}")
    expect(screen.queryByText("failed")).toBeNull()
  })

  it("AC16.19.9 auto-expires notifications", async () => {
    render(
      <ToastProvider>
        <TestToastConsumer />
      </ToastProvider>,
    )

    fireEvent.click(screen.getByRole("button", { name: "Show Error" }))
    expect(screen.getByText("failed")).toBeInTheDocument()

    await new Promise((resolve) => setTimeout(resolve, 3200))
    await waitFor(() => expect(screen.queryByText("failed")).toBeNull())
  })
})

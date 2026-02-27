import { fireEvent, render, screen, waitFor } from "@testing-library/react"
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

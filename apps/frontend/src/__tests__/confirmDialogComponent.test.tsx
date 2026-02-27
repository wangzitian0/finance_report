import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import ConfirmDialog from "@/components/ui/ConfirmDialog"

describe("ConfirmDialog component", () => {
  it("AC16.19.7 handles required input and confirm/cancel", () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()

    render(
      <ConfirmDialog
        isOpen
        title="Reject"
        message="Provide reason"
        showInput
        inputRequired
        confirmLabel="Reject"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )

    const confirmButton = screen.getByRole("button", { name: "Reject" }) as HTMLButtonElement
    expect(confirmButton.disabled).toBe(true)

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "bad data" } })
    expect(confirmButton.disabled).toBe(false)

    fireEvent.click(confirmButton)
    expect(onConfirm).toHaveBeenCalledWith("bad data")

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it("AC16.19.8 handles escape and backdrop cancellation", () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()

    const { container } = render(
      <ConfirmDialog isOpen title="Approve" message="Proceed" onConfirm={onConfirm} onCancel={onCancel} />,
    )

    fireEvent.keyDown(document, { key: "Escape" })
    expect(onCancel).toHaveBeenCalledTimes(1)

    const backdrop = container.querySelector("[aria-hidden='true']")
    expect(backdrop).not.toBeNull()
    if (backdrop) fireEvent.click(backdrop)
    expect(onCancel).toHaveBeenCalledTimes(2)
  })
})

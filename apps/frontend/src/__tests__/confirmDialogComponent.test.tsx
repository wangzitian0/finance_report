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

  it("renders dialog with ARIA attributes", () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()

    render(
      <ConfirmDialog isOpen title="Test" message="Message" onConfirm={onConfirm} onCancel={onCancel} />,
    )

    const dialog = screen.getByRole("dialog")
    expect(dialog).toHaveAttribute("aria-modal", "true")
    expect(dialog).toHaveAttribute("aria-labelledby")
  })

  it("blocks escape and backdrop when loading", () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()

    const { container } = render(
      <ConfirmDialog isOpen loading title="Working" message="Wait" onConfirm={onConfirm} onCancel={onCancel} />,
    )

    fireEvent.keyDown(document, { key: "Escape" })
    expect(onCancel).not.toHaveBeenCalled()

    const backdrop = container.querySelector("[aria-hidden='true']")
    if (backdrop) fireEvent.click(backdrop)
    expect(onCancel).not.toHaveBeenCalled()

    expect(screen.getByText("Processing...")).toBeInTheDocument()
  })

  it("renders nothing when not open", () => {
    const { container } = render(
      <ConfirmDialog isOpen={false} title="T" message="M" onConfirm={vi.fn()} onCancel={vi.fn()} />,
    )
    expect(container.querySelector("[role='dialog']")).toBeNull()
  })

  it("shows danger variant styling", () => {
    render(
      <ConfirmDialog isOpen title="Delete" message="Sure?" confirmVariant="danger" confirmLabel="Delete" onConfirm={vi.fn()} onCancel={vi.fn()} />,
    )
    const deleteButton = screen.getByRole("button", { name: "Delete" })
    expect(deleteButton.className).toContain("--error")
  })

  it("shows input label with required indicator", () => {
    render(
      <ConfirmDialog isOpen title="T" message="M" showInput inputRequired inputLabel="Reason" onConfirm={vi.fn()} onCancel={vi.fn()} />,
    )
    expect(screen.getByText("Reason")).toBeInTheDocument()
    expect(screen.getByText("*")).toBeInTheDocument()
  })

  it("passes input value on confirm without required", () => {
    const onConfirm = vi.fn()
    render(
      <ConfirmDialog isOpen title="T" message="M" showInput onConfirm={onConfirm} onCancel={vi.fn()} />,
    )
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "note" } })
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }))
    expect(onConfirm).toHaveBeenCalledWith("note")
  })

  it("renders children slot", () => {
    render(
      <ConfirmDialog isOpen title="T" message="M" onConfirm={vi.fn()} onCancel={vi.fn()}>
        <p>Extra info</p>
      </ConfirmDialog>,
    )
    expect(screen.getByText("Extra info")).toBeInTheDocument()
  })

  it("traps focus with Tab and Shift+Tab", () => {
    render(
      <ConfirmDialog isOpen title="Focus" message="Trap" showInput onConfirm={vi.fn()} onCancel={vi.fn()} />,
    )

    const dialog = screen.getByRole("dialog")
    const buttons = dialog.querySelectorAll<HTMLElement>("button, textarea")
    const first = buttons[0]
    const last = buttons[buttons.length - 1]

    // Focus first element, then Shift+Tab should wrap to last
    first?.focus()
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true })
    expect(document.activeElement).toBe(last)

    // Focus last element, then Tab should wrap to first
    last?.focus()
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: false })
    expect(document.activeElement).toBe(first)

    // Non-Tab key should not affect focus
    first?.focus()
    fireEvent.keyDown(dialog, { key: "a" })
    expect(document.activeElement).toBe(first)
  })
})

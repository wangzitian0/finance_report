import "@testing-library/jest-dom/vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import Sheet from "@/components/ui/Sheet"
import DetailDialog from "@/components/ui/DetailDialog"

vi.mock("@/hooks/useFocusTrap", () => ({ useFocusTrap: vi.fn() }))

describe("Sheet component", () => {
  it("renders nothing when isOpen=false", () => {
    const { container } = render(<Sheet isOpen={false} onClose={vi.fn()} title="T">x</Sheet>)
    expect(container.querySelector("[role='dialog']")).toBeNull()
  })

  it("renders dialog with title and children when open", () => {
    render(<Sheet isOpen onClose={vi.fn()} title="My Sheet"><div>child</div></Sheet>)
    const dialog = screen.getByRole("dialog")
    expect(dialog).toBeInTheDocument()
    expect(screen.getByText("My Sheet")).toBeInTheDocument()
    expect(screen.getByText("child")).toBeInTheDocument()
    expect(dialog).toHaveAttribute("aria-modal", "true")
  })

  it("calls onClose when close button clicked", () => {
    const onClose = vi.fn()
    render(<Sheet isOpen onClose={onClose} title="S">ok</Sheet>)
    fireEvent.click(screen.getByRole("button", { name: /Close panel/i }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("calls onClose when backdrop clicked", () => {
    const onClose = vi.fn()
    const { container } = render(<Sheet isOpen onClose={onClose} title="S">ok</Sheet>)
    const backdrop = container.querySelector("[aria-hidden='true']")
    expect(backdrop).not.toBeNull()
    if (backdrop) fireEvent.click(backdrop)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("calls onClose when Escape key pressed", () => {
    const onClose = vi.fn()
    render(<Sheet isOpen onClose={onClose} title="S">ok</Sheet>)
    fireEvent.keyDown(document, { key: "Escape" })
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

describe("DetailDialog component", () => {
  it("renders nothing when isOpen=false", () => {
    const { container } = render(<DetailDialog isOpen={false} onClose={vi.fn()} title="T">x</DetailDialog>)
    expect(container.querySelector("[role='dialog']")).toBeNull()
  })

  it("renders dialog with title and children when open", () => {
    render(<DetailDialog isOpen onClose={vi.fn()} title="My Dialog"><p>abc</p></DetailDialog>)
    const dialog = screen.getByRole("dialog")
    expect(dialog).toBeInTheDocument()
    expect(screen.getByText("My Dialog")).toBeInTheDocument()
    expect(screen.getByText("abc")).toBeInTheDocument()
    expect(dialog).toHaveAttribute("aria-modal", "true")
  })

  it("calls onClose when close button clicked", () => {
    const onClose = vi.fn()
    render(<DetailDialog isOpen onClose={onClose} title="D">ok</DetailDialog>)
    fireEvent.click(screen.getByRole("button", { name: /Close modal/i }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("calls onClose when backdrop clicked", () => {
    const onClose = vi.fn()
    const { container } = render(<DetailDialog isOpen onClose={onClose} title="D">ok</DetailDialog>)
    const backdrop = container.querySelector("[aria-hidden='true']")
    expect(backdrop).not.toBeNull()
    if (backdrop) fireEvent.click(backdrop)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("calls onClose when Escape key pressed", () => {
    const onClose = vi.fn()
    render(<DetailDialog isOpen onClose={onClose} title="D">ok</DetailDialog>)
    fireEvent.keyDown(document, { key: "Escape" })
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

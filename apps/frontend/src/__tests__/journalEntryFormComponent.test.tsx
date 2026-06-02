import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import JournalEntryForm from "@/components/journal/JournalEntryForm"
import { apiFetch } from "@/lib/api"

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

describe("JournalEntryForm", () => {
  const mockedApiFetch = vi.mocked(apiFetch)
  const onClose = vi.fn()
  const onSuccess = vi.fn()

  beforeEach(() => {
    mockedApiFetch.mockReset()
    onClose.mockReset()
    onSuccess.mockReset()
  })

  it("AC16.21.4 loads account options and shows balanced/unbalanced state", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      items: [
        { id: "a1", name: "Cash", code: "1000", type: "ASSET", currency: "SGD", is_active: true, balance: 0 },
        { id: "a2", name: "Revenue", code: "4000", type: "INCOME", currency: "SGD", is_active: true, balance: 0 },
      ],
    })

    render(<JournalEntryForm isOpen onClose={onClose} onSuccess={onSuccess} />)

    expect(await screen.findAllByRole("option", { name: "1000 - Cash" })).toHaveLength(2)
    expect(screen.getByText("✓ Balanced in SGD")).toBeInTheDocument()

    const amountInputs = screen.getAllByPlaceholderText("0.00")
    fireEvent.change(amountInputs[0], { target: { value: "100" } })
    expect(screen.getByText("⚠ Unbalanced or missing FX")).toBeInTheDocument()

    fireEvent.change(amountInputs[1], { target: { value: "100" } })
    expect(screen.getByText("✓ Balanced in SGD")).toBeInTheDocument()
  })

  it("AC2.12.1 balances multi-currency lines using SGD base amounts", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [
          { id: "a1", name: "USD Bank", code: "1010", type: "ASSET", currency: "USD", is_active: true, balance: 0 },
          { id: "a2", name: "Owner Equity", code: "3000", type: "EQUITY", currency: "SGD", is_active: true, balance: 0 },
        ],
      })
      .mockResolvedValueOnce({ id: "je-fx" })

    const { container } = render(<JournalEntryForm isOpen onClose={onClose} onSuccess={onSuccess} />)

    await screen.findAllByRole("option", { name: "1010 - USD Bank" })
    fireEvent.change(screen.getByPlaceholderText("Description"), { target: { value: "USD capital" } })

    const lineSelects = screen.getAllByRole("combobox")
    fireEvent.change(lineSelects[0], { target: { value: "a1" } })
    fireEvent.change(lineSelects[2], { target: { value: "a2" } })

    fireEvent.change(screen.getByLabelText("Line 1 amount"), { target: { value: "100" } })
    fireEvent.change(screen.getByLabelText("Line 1 currency"), { target: { value: "USD" } })
    expect(screen.getByText("⚠ Unbalanced or missing FX")).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText("Line 1 FX rate"), { target: { value: "1.35" } })
    fireEvent.change(screen.getByLabelText("Line 2 amount"), { target: { value: "135" } })
    expect(screen.getByText("✓ Balanced in SGD")).toBeInTheDocument()

    fireEvent.submit(container.querySelector("form") as HTMLFormElement)

    await waitFor(() => {
      const createCall = mockedApiFetch.mock.calls.find((call) => call[0] === "/api/journal-entries")
      expect(createCall).toBeDefined()
      const request = createCall?.[1] as { method: string; body: string }
      const body = JSON.parse(request.body)
      expect(body.lines).toEqual([
        { account_id: "a1", direction: "DEBIT", amount: "100.00", currency: "USD", fx_rate: "1.350000" },
        { account_id: "a2", direction: "CREDIT", amount: "135.00", currency: "SGD" },
      ])
    })
  })

  it("AC16.21.6 supports add and remove line interactions", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      items: [{ id: "a1", name: "Cash", code: "1000", type: "ASSET", currency: "SGD", is_active: true, balance: 0 }],
    })

    const { container } = render(<JournalEntryForm isOpen onClose={onClose} onSuccess={onSuccess} />)

    await screen.findAllByRole("option", { name: "1000 - Cash" })
    expect(screen.getAllByPlaceholderText("0.00")).toHaveLength(2)

    fireEvent.click(screen.getByRole("button", { name: "+ Add Line" }))
    expect(screen.getAllByPlaceholderText("0.00")).toHaveLength(3)

    const removeButtons = container.querySelectorAll("button.btn-ghost")
    expect(removeButtons.length).toBeGreaterThan(0)
    fireEvent.click(removeButtons[0] as HTMLButtonElement)

    expect(screen.getAllByPlaceholderText("0.00")).toHaveLength(2)
  })

  it("AC16.21.6 handles account option load failures", async () => {
    mockedApiFetch.mockRejectedValueOnce(new Error("accounts unavailable"))

    render(<JournalEntryForm isOpen onClose={onClose} onSuccess={onSuccess} />)

    await waitFor(() => {
      expect(screen.getAllByRole("option", { name: "Select Account" })).toHaveLength(2)
    })
    expect(screen.queryByRole("option", { name: "1000 - Cash" })).not.toBeInTheDocument()
  })

  it("AC16.21.5 submits create-draft payload with normalized amounts", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [
          { id: "a1", name: "Cash", code: "1000", type: "ASSET", currency: "SGD", is_active: true, balance: 0 },
          { id: "a2", name: "Revenue", code: "4000", type: "INCOME", currency: "SGD", is_active: true, balance: 0 },
        ],
      })
      .mockResolvedValueOnce({ id: "je1" })

    const { container } = render(<JournalEntryForm isOpen onClose={onClose} onSuccess={onSuccess} />)

    await screen.findAllByRole("option", { name: "1000 - Cash" })
    const dateInput = container.querySelector("input[name='entry_date']") as HTMLInputElement
    fireEvent.change(dateInput, { target: { value: "2026-02-01" } })
    fireEvent.change(screen.getByPlaceholderText("Description"), { target: { value: "Manual adjustment" } })

    const lineSelects = screen.getAllByRole("combobox")
    fireEvent.change(lineSelects[0], { target: { value: "a1" } })
    fireEvent.change(lineSelects[2], { target: { value: "a2" } })

    const amountInputs = screen.getAllByPlaceholderText("0.00")
    fireEvent.change(amountInputs[0], { target: { value: "120" } })
    fireEvent.change(amountInputs[1], { target: { value: "120" } })

    fireEvent.submit(container.querySelector("form") as HTMLFormElement)

    await waitFor(() => {
      const createCall = mockedApiFetch.mock.calls.find((call) => call[0] === "/api/journal-entries")
      expect(createCall).toBeDefined()
      const request = createCall?.[1] as { method: string; body: string }
      expect(request.method).toBe("POST")
      const body = JSON.parse(request.body)
      expect(body.memo).toBe("Manual adjustment")
      expect(body.source_type).toBe("manual")
      expect(body.lines).toEqual([
        { account_id: "a1", direction: "DEBIT", amount: "120.00", currency: "SGD" },
        { account_id: "a2", direction: "CREDIT", amount: "120.00", currency: "SGD" },
      ])
    })
    expect(onSuccess).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("AC16.21.5 posts immediately when checkbox is enabled", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [
          { id: "a1", name: "Cash", code: "1000", type: "ASSET", currency: "SGD", is_active: true, balance: 0 },
          { id: "a2", name: "Revenue", code: "4000", type: "INCOME", currency: "SGD", is_active: true, balance: 0 },
        ],
      })
      .mockResolvedValueOnce({ id: "je-post" })
      .mockResolvedValueOnce({})

    const { container } = render(<JournalEntryForm isOpen onClose={onClose} onSuccess={onSuccess} />)

    await screen.findAllByRole("option", { name: "1000 - Cash" })
    const dateInput = container.querySelector("input[name='entry_date']") as HTMLInputElement
    fireEvent.change(dateInput, { target: { value: "2026-02-02" } })
    fireEvent.change(screen.getByPlaceholderText("Description"), { target: { value: "Immediate post" } })

    const lineSelects = screen.getAllByRole("combobox")
    fireEvent.change(lineSelects[0], { target: { value: "a1" } })
    fireEvent.change(lineSelects[2], { target: { value: "a2" } })

    const amountInputs = screen.getAllByPlaceholderText("0.00")
    fireEvent.change(amountInputs[0], { target: { value: "88" } })
    fireEvent.change(amountInputs[1], { target: { value: "88" } })

    fireEvent.click(screen.getByLabelText("Post transaction immediately"))
    expect(screen.getByRole("button", { name: "Create & Post" })).toBeInTheDocument()

    fireEvent.submit(container.querySelector("form") as HTMLFormElement)

    await waitFor(() => {
      expect(mockedApiFetch.mock.calls.some((call) => call[0] === "/api/journal-entries/je-post/post")).toBe(true)
    })
  })

  it("AC16.21.6 surfaces form-level and API errors", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      items: [
        { id: "a1", name: "Cash", code: "1000", type: "ASSET", currency: "SGD", is_active: true, balance: 0 },
        { id: "a2", name: "Revenue", code: "4000", type: "INCOME", currency: "SGD", is_active: true, balance: 0 },
      ],
    })

    const { container } = render(<JournalEntryForm isOpen onClose={onClose} onSuccess={onSuccess} />)

    await screen.findAllByRole("option", { name: "1000 - Cash" })
    fireEvent.click(screen.getByRole("button", { name: "Create Draft" }))

    expect(await screen.findByText("Memo is required")).toBeInTheDocument()

    mockedApiFetch.mockRejectedValueOnce(new Error("create entry failed"))
    const dateInput = container.querySelector("input[name='entry_date']") as HTMLInputElement
    fireEvent.change(dateInput, { target: { value: "2026-02-03" } })
    fireEvent.change(screen.getByPlaceholderText("Description"), { target: { value: "Try submit" } })

    const lineSelects = screen.getAllByRole("combobox")
    fireEvent.change(lineSelects[0], { target: { value: "a1" } })
    fireEvent.change(lineSelects[2], { target: { value: "a2" } })

    const amountInputs = screen.getAllByPlaceholderText("0.00")
    fireEvent.change(amountInputs[0], { target: { value: "50" } })
    fireEvent.change(amountInputs[1], { target: { value: "50" } })

    fireEvent.submit(container.querySelector("form") as HTMLFormElement)
    await waitFor(() => {
      expect(mockedApiFetch.mock.calls.some((call) => call[0] === "/api/journal-entries")).toBe(true)
    })
    expect(await screen.findByText("create entry failed")).toBeInTheDocument()
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it("does not render when isOpen is false", () => {
    const { container } = render(<JournalEntryForm isOpen={false} onClose={onClose} onSuccess={onSuccess} />)
    expect(container.firstChild).toBeNull()
  })
})

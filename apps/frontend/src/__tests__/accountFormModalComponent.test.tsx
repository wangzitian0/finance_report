import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import AccountFormModal from "@/components/accounts/AccountFormModal"
import { apiFetch } from "@/lib/api"

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

describe("AccountFormModal", () => {
  const mockedApiFetch = vi.mocked(apiFetch)
  const onClose = vi.fn()
  const onSuccess = vi.fn()

  beforeEach(() => {
    mockedApiFetch.mockReset()
    onClose.mockReset()
    onSuccess.mockReset()
  })

  it("AC16.21.1 create mode submits normalized payload and closes on success", async () => {
    mockedApiFetch.mockResolvedValueOnce({ id: "a1" })

    render(<AccountFormModal isOpen onClose={onClose} onSuccess={onSuccess} />)

    fireEvent.change(screen.getByPlaceholderText("e.g., Cash on Hand"), { target: { value: "Cash Box" } })
    fireEvent.change(screen.getByPlaceholderText("e.g., 1000"), { target: { value: "" } })

    const comboboxes = screen.getAllByRole("combobox")
    fireEvent.change(comboboxes[0], { target: { value: "ASSET" } })
    fireEvent.change(comboboxes[1], { target: { value: "USD" } })

    fireEvent.change(screen.getByPlaceholderText("Optional description..."), { target: { value: "" } })
    fireEvent.click(screen.getByRole("button", { name: "Create Account" }))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/accounts", {
        method: "POST",
        body: JSON.stringify({
          name: "Cash Box",
          code: null,
          type: "ASSET",
          currency: "USD",
          description: null,
        }),
      }),
    )
    expect(onSuccess).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("AC16.21.2 edit mode pre-fills values and submits update payload", async () => {
    mockedApiFetch.mockResolvedValueOnce({ id: "a1" })

    render(
      <AccountFormModal
        isOpen
        onClose={onClose}
        onSuccess={onSuccess}
        editAccount={{
          id: "a1",
          name: "Old Name",
          type: "ASSET",
          currency: "SGD",
          is_active: true,
          code: "1000",
          description: undefined,
          balance: 0,
        }}
      />,
    )

    const nameInput = screen.getByDisplayValue("Old Name")
    fireEvent.change(nameInput, { target: { value: "Renamed" } })
    fireEvent.change(screen.getByDisplayValue("1000"), { target: { value: "1100" } })
    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }))

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/accounts/a1", {
        method: "PUT",
        body: JSON.stringify({
          name: "Renamed",
          code: "1100",
          is_active: true,
        }),
      }),
    )
    expect(onSuccess).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("AC16.21.3 shows validation and API errors in create flow", async () => {
    mockedApiFetch.mockRejectedValueOnce(new Error("create failed"))

    render(<AccountFormModal isOpen onClose={onClose} onSuccess={onSuccess} />)

    fireEvent.click(screen.getByRole("button", { name: "Create Account" }))
    expect(await screen.findByText("Account name is required")).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText("e.g., Cash on Hand"), { target: { value: "Cash" } })
    fireEvent.click(screen.getByRole("button", { name: "Create Account" }))

    expect(await screen.findByText("create failed")).toBeInTheDocument()
    expect(onSuccess).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })

  it("AC16.21.3 shows API errors in edit flow", async () => {
    mockedApiFetch.mockRejectedValueOnce(new Error("update failed"))

    render(
      <AccountFormModal
        isOpen
        onClose={onClose}
        onSuccess={onSuccess}
        editAccount={{
          id: "a2",
          name: "Payable",
          type: "LIABILITY",
          currency: "SGD",
          is_active: false,
          code: undefined,
          description: undefined,
          balance: 0,
        }}
      />,
    )

    fireEvent.change(screen.getByDisplayValue("Payable"), { target: { value: "Accounts Payable" } })
    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }))

    expect(await screen.findByText("update failed")).toBeInTheDocument()
    expect(onSuccess).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })

  it("renders nothing when closed", () => {
    const { container } = render(<AccountFormModal isOpen={false} onClose={onClose} onSuccess={onSuccess} />)
    expect(container.firstChild).toBeNull()
  })
})

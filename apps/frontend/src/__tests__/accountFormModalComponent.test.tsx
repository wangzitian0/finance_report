import { useLayoutEffect } from "react"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import AccountFormModal from "@/components/accounts/AccountFormModal"
import { apiOperation } from "@/lib/api-client"

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}))

describe("AccountFormModal", () => {
  const mockedApiOperation = vi.mocked(apiOperation)
  const onClose = vi.fn()
  const onSuccess = vi.fn()

  beforeEach(() => {
    mockedApiOperation.mockReset()
    onClose.mockReset()
    onSuccess.mockReset()
  })

  // AC-ledger.fe-accounts-journal.12
  it("AC16.21.1 create mode submits normalized payload and closes on success", async () => {
    mockedApiOperation.mockResolvedValueOnce({ id: "a1" } as any)

    render(<AccountFormModal isOpen onClose={onClose} onSuccess={onSuccess} />)

    fireEvent.change(screen.getByPlaceholderText("e.g., Cash on Hand"), { target: { value: "Cash Box" } })
    fireEvent.change(screen.getByPlaceholderText("e.g., 1000"), { target: { value: "" } })

    fireEvent.change(screen.getByLabelText("Type *"), { target: { value: "ASSET" } })
    fireEvent.change(screen.getByLabelText("Currency *"), { target: { value: "USD" } })

    fireEvent.change(screen.getByPlaceholderText("Optional description..."), { target: { value: "" } })
    fireEvent.click(screen.getByRole("button", { name: "Create Account" }))

    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith("create_account_accounts_post", {
        body: {
          name: "Cash Box",
          code: null,
          type: "ASSET",
          currency: "USD",
          description: null,
        },
      }),
    )
    expect(onSuccess).toHaveBeenCalledTimes(1)
    expect(onSuccess).toHaveBeenCalledWith({ id: "a1" })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  // AC-ledger.fe-accounts-journal.12: enter at the first committed DOM,
  // before passive effects run, matching fast interaction after reopening.
  it("preserves first input while a reopened account form becomes interactive", async () => {
    mockedApiOperation.mockResolvedValue({ id: "generated-account" } as any)

    function FirstInteraction({ open, name, type }: { open: boolean; name: string; type: string }) {
      useLayoutEffect(() => {
        if (!open) return
        fireEvent.change(screen.getByPlaceholderText("e.g., Cash on Hand"), { target: { value: name } })
        fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: type } })
      }, [open, name, type])
      return <AccountFormModal isOpen={open} onClose={onClose} onSuccess={onSuccess} />
    }

    const { rerender } = render(<FirstInteraction open={false} name="" type="ASSET" />)
    for (const type of ["ASSET", "INCOME", "EXPENSE"]) {
      const name = `Generated ${type}`
      rerender(<FirstInteraction open name={name} type={type} />)
      expect(screen.getByPlaceholderText("e.g., Cash on Hand")).toHaveValue(name)
      expect(screen.getAllByRole("combobox")[0]).toHaveValue(type)
      fireEvent.click(screen.getByRole("button", { name: "Create Account" }))
      await waitFor(() =>
        expect(mockedApiOperation).toHaveBeenLastCalledWith("create_account_accounts_post", {
          body: { name, code: null, type, currency: "SGD", description: null },
        }),
      )
      rerender(<FirstInteraction open={false} name={name} type={type} />)
    }
    expect(mockedApiOperation).toHaveBeenCalledTimes(3)
  })

  // AC-ledger.fe-accounts-journal.13
  it("AC16.21.2 edit mode pre-fills values and submits update payload", async () => {
    mockedApiOperation.mockResolvedValueOnce({ id: "a1" } as any)

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
          balance: "0",
          is_system: false,
          user_id: "u1",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }}
      />,
    )

    const nameInput = screen.getByDisplayValue("Old Name")
    fireEvent.change(nameInput, { target: { value: "Renamed" } })
    fireEvent.change(screen.getByDisplayValue("1000"), { target: { value: "1100" } })
    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }))

    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith("update_account_accounts__account_id__put", {
        path: { account_id: "a1" },
        body: {
          name: "Renamed",
          code: "1100",
          is_active: true,
        },
      }),
    )
    expect(onSuccess).toHaveBeenCalledTimes(1)
    expect(onSuccess).toHaveBeenCalledWith({ id: "a1" })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  // AC-ledger.fe-accounts-journal.14
  it("AC16.21.3 shows validation and API errors in create flow", async () => {
    mockedApiOperation.mockRejectedValueOnce(new Error("create failed"))

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
    mockedApiOperation.mockRejectedValueOnce(new Error("update failed"))

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
          balance: "0",
          is_system: false,
          user_id: "u1",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
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

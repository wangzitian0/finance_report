import "@testing-library/jest-dom/vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import AccountsPage from "@/app/(main)/accounts/page"
import { apiFetch } from "@/lib/api"
import type { Account, AccountListResponse } from "@/lib/types"

const showToastMock = vi.fn()

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))


vi.mock("@/components/ui/ConfirmDialog", () => ({
  default: ({ isOpen, onConfirm, onCancel, title }: { isOpen: boolean; onConfirm: () => void; onCancel: () => void; title?: string; message?: string; confirmLabel?: string; confirmVariant?: string }) =>
    isOpen ? (
      <div data-testid="confirm-dialog">
        <span>{title}</span>
        <button onClick={onConfirm}>Confirm Delete</button>
        <button onClick={onCancel}>Cancel Delete</button>
      </div>
    ) : null,
}))
vi.mock("@/components/accounts/AccountFormModal", () => ({
  default: ({ isOpen, editAccount, onSuccess, onClose }: { isOpen: boolean; editAccount: Account | null; onSuccess?: () => void; onClose?: () => void }) =>
    isOpen ? (
      <div>
        {editAccount ? `Edit:${editAccount.name}` : "Create Account Modal"}
        {onSuccess && <button onClick={onSuccess}>Mock Save</button>}
        {onClose && <button onClick={onClose}>Mock Close</button>}
      </div>
    ) : null,
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  const TestWrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  TestWrapper.displayName = "AccountsTestWrapper"
  return TestWrapper
}

describe("AccountsPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
  })

  it("AC16.15.1 renders loading and error retry states", async () => {
    mockedApiFetch.mockRejectedValue(new Error("accounts failed"))

    render(<AccountsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("Failed to load accounts")).not.toBeNull())
    fireEvent.click(screen.getByRole("button", { name: "Retry loading accounts" }))
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(2))
  })

  it("AC16.15.2 renders grouped accounts and supports type filters", async () => {
    mockedApiFetch.mockResolvedValue({
      items: [
        { id: "a1", name: "Cash", type: "ASSET", currency: "SGD", is_active: true, balance: 1000, code: "1000" },
        { id: "a2", name: "Salary", type: "INCOME", currency: "SGD", is_active: true, balance: 2000, code: "4000" },
      ],
      total: 2,
    } satisfies AccountListResponse)

    render(<AccountsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("Cash")).not.toBeNull())
    expect(screen.queryByText("Salary")).not.toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "INCOME" }))
    expect(screen.queryByText("Cash")).toBeNull()
    expect(screen.queryByText("Salary")).not.toBeNull()
  })

  it("AC16.15.3 delete action confirms and calls delete API with success toast", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [{ id: "a1", name: "Cash", type: "ASSET", currency: "SGD", is_active: true, balance: 1000 }],
        total: 1,
      } satisfies AccountListResponse)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce({ items: [], total: 0 } satisfies AccountListResponse)

    render(<AccountsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("Cash")).not.toBeNull())
    fireEvent.click(screen.getByTitle("Delete Account"))
    // ConfirmDialog should now be open
    await waitFor(() => expect(screen.getByTestId("confirm-dialog")).toBeInTheDocument())
    fireEvent.click(screen.getByText("Confirm Delete"))

    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/accounts/a1", { method: "DELETE" })
    })
    expect(showToastMock).toHaveBeenCalledWith("Account deleted successfully", "success")
    await waitFor(() => expect(screen.queryByText("Cash")).toBeNull())
  })

  it("AC16.15.4 delete error shows error toast", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [{ id: "a1", name: "Cash", type: "ASSET", currency: "SGD", is_active: true, balance: 1000 }],
        total: 1,
      } satisfies AccountListResponse)
      .mockRejectedValueOnce(new Error("Cannot delete account with transactions"))
    render(<AccountsPage />, { wrapper: createWrapper() })
    await waitFor(() => expect(screen.queryByText("Cash")).not.toBeNull())
    fireEvent.click(screen.getByTitle("Delete Account"))
    await waitFor(() => expect(screen.getByTestId("confirm-dialog")).toBeInTheDocument())
    fireEvent.click(screen.getByText("Confirm Delete"))
    await waitFor(() => {
      expect(showToastMock).toHaveBeenCalledWith(
        "Failed to delete account: Cannot delete account with transactions",
        "error",
      )
    })
  })

  it("AC16.15.5 shows empty state with create button", async () => {
    mockedApiFetch.mockResolvedValueOnce({ items: [], total: 0 } satisfies AccountListResponse)

    render(<AccountsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("No accounts yet")).toBeInTheDocument())
    expect(screen.getByText("Create First Account")).toBeInTheDocument()

    fireEvent.click(screen.getByText("Create First Account"))
    expect(screen.getByText("Create Account Modal")).toBeInTheDocument()
  })

  it("AC16.15.6 cancel delete dialog closes without API call", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      items: [{ id: "a1", name: "Cash", type: "ASSET", currency: "SGD", is_active: true, balance: 1000 }],
      total: 1,
    } satisfies AccountListResponse)

    render(<AccountsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("Cash")).not.toBeNull())
    fireEvent.click(screen.getByTitle("Delete Account"))
    await waitFor(() => expect(screen.getByTestId("confirm-dialog")).toBeInTheDocument())
    fireEvent.click(screen.getByText("Cancel Delete"))

    await waitFor(() => expect(screen.queryByTestId("confirm-dialog")).toBeNull())
    expect(mockedApiFetch).toHaveBeenCalledTimes(1)
  })

  it("AC16.15.7 edit button opens modal with account data", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      items: [{ id: "a1", name: "Cash", type: "ASSET", currency: "SGD", is_active: true, balance: 1000 }],
      total: 1,
    } satisfies AccountListResponse)

    render(<AccountsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("Cash")).not.toBeNull())
    fireEvent.click(screen.getByTitle("Edit Account"))
    expect(screen.getByText("Edit:Cash")).toBeInTheDocument()
  })

  it("AC16.15.8 Add Account button opens create modal", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      items: [{ id: "a1", name: "Cash", type: "ASSET", currency: "SGD", is_active: true, balance: 1000 }],
      total: 1,
    } satisfies AccountListResponse)

    render(<AccountsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("Cash")).not.toBeNull())
    fireEvent.click(screen.getByText("Add Account"))
    expect(screen.getByText("Create Account Modal")).toBeInTheDocument()
  })

  it("AC16.15.9 modal onSuccess triggers account list refresh", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [{ id: "a1", name: "Cash", type: "ASSET", currency: "SGD", is_active: true, balance: 1000 }],
        total: 1,
      } satisfies AccountListResponse)
      .mockResolvedValueOnce({
        items: [
          { id: "a1", name: "Cash", type: "ASSET", currency: "SGD", is_active: true, balance: 1000 },
          { id: "a2", name: "Savings", type: "ASSET", currency: "SGD", is_active: true, balance: 5000 },
        ],
        total: 2,
      } satisfies AccountListResponse)

    render(<AccountsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("Cash")).not.toBeNull())
    fireEvent.click(screen.getByText("Add Account"))
    expect(screen.getByText("Create Account Modal")).toBeInTheDocument()

    fireEvent.click(screen.getByText("Mock Save"))

    await waitFor(() => expect(screen.getByText("Savings")).toBeInTheDocument())
  })

  it("AC16.15.10 modal onClose closes modal and clears editing state", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      items: [{ id: "a1", name: "Cash", type: "ASSET", currency: "SGD", is_active: true, balance: 1000 }],
      total: 1,
    } satisfies AccountListResponse)

    render(<AccountsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("Cash")).not.toBeNull())
    fireEvent.click(screen.getByTitle("Edit Account"))
    expect(screen.getByText("Edit:Cash")).toBeInTheDocument()

    fireEvent.click(screen.getByText("Mock Close"))

    await waitFor(() => expect(screen.queryByText("Edit:Cash")).toBeNull())
    expect(screen.queryByText("Create Account Modal")).toBeNull()
  })
})
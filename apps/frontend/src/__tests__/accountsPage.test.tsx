import "@testing-library/jest-dom/vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import AccountsPage from "@/app/(main)/accounts/page"
import { apiFetch } from "@/lib/api"
import type { Account, AccountListResponse } from "@/lib/types"

const showToastMock = vi.fn()

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock("@/components/accounts/AccountFormModal", () => ({
  default: ({ isOpen, editAccount }: { isOpen: boolean; editAccount: Account | null }) =>
    isOpen ? <div>{editAccount ? `Edit:${editAccount.name}` : "Create Account Modal"}</div> : null,
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
    vi.stubGlobal("confirm", vi.fn(() => true))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
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

    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/accounts/a1", { method: "DELETE" })
    })
    expect(showToastMock).toHaveBeenCalledWith("Account deleted successfully", "success")
    await waitFor(() => expect(screen.queryByText("Cash")).toBeNull())
  })
})

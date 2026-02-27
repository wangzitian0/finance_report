import "@testing-library/jest-dom/vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import AssetsPage from "@/app/(main)/assets/page"
import { apiFetch } from "@/lib/api"
import type { ManagedPosition, ManagedPositionListResponse, ReconcilePositionsResponse } from "@/lib/types"

const showToastMock = vi.fn()

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
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
  TestWrapper.displayName = "AssetsTestWrapper"
  return TestWrapper
}

describe("AssetsPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("AC16.15.4 renders loading and error retry states", async () => {
    mockedApiFetch.mockRejectedValue(new Error("positions failed"))

    render(<AssetsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("Failed to load positions")).not.toBeNull())
    fireEvent.click(screen.getByRole("button", { name: "Retry loading positions" }))
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(2))
  })

  it("AC16.15.5 renders grouped positions and supports status filters", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.includes("status_filter=disposed")) {
        return Promise.resolve({
          items: [
            {
              id: "p2",
              user_id: "u1",
              account_id: "acc1",
              account_name: "IBKR",
              asset_identifier: "TSLA",
              quantity: "5",
              cost_basis: "1000",
              acquisition_date: "2025-01-01",
              disposal_date: "2025-12-01",
              status: "disposed",
              currency: "USD",
              created_at: "2025-01-01",
              updated_at: "2025-12-01",
            },
          ],
          total: 1,
        } satisfies ManagedPositionListResponse)
      }

      return Promise.resolve({
        items: [
          {
            id: "p1",
            user_id: "u1",
            account_id: "acc1",
            account_name: "IBKR",
            asset_identifier: "AAPL",
            quantity: "10",
            cost_basis: "1500",
            acquisition_date: "2025-01-01",
            disposal_date: null,
            status: "active",
            currency: "USD",
            created_at: "2025-01-01",
            updated_at: "2025-01-02",
          },
        ],
        total: 1,
      } satisfies ManagedPositionListResponse)
    })

    render(<AssetsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("AAPL")).not.toBeNull())
    expect(screen.queryByText("IBKR")).not.toBeNull()
    expect(screen.queryByText(/Total Value:/)).not.toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "disposed" }))
    await waitFor(() => expect(screen.queryByText("TSLA")).not.toBeNull())
    expect(screen.queryByText("AAPL")).toBeNull()
    expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("status_filter=disposed"))
  })

  it("AC16.15.6 reconcile action calls API and shows toast summary", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({ items: [], total: 0 } satisfies ManagedPositionListResponse)
      .mockResolvedValueOnce({
        message: "done",
        created: 1,
        updated: 2,
        disposed: 0,
        skipped: 0,
        skipped_assets: [],
      } satisfies ReconcilePositionsResponse)
      .mockResolvedValueOnce({ items: [], total: 0 } satisfies ManagedPositionListResponse)

    render(<AssetsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("No positions found")).not.toBeNull())
    fireEvent.click(screen.getByRole("button", { name: "Reconcile Positions" }))

    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/assets/reconcile", { method: "POST" })
    })
    expect(showToastMock).toHaveBeenCalledWith("Reconciled 3 positions (1 created, 2 updated, 0 disposed)", "success")
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("/api/assets/positions")))
  })
})

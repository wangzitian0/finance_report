import "@testing-library/jest-dom/vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import AssetsPage from "@/app/(main)/assets/page"
import { apiFetch } from "@/lib/api"
import type {
  ManagedPosition,
  ManagedPositionListResponse,
  ManualValuationSnapshotListResponse,
  ReconcilePositionsResponse,
} from "@/lib/types"

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

  const emptyValuations: ManualValuationSnapshotListResponse = {
    items: [],
    total: 0,
  }

  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
    mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("/api/assets/valuation-snapshots") && !options) {
        return Promise.resolve(emptyValuations)
      }
      if (path === "/api/assets/valuation-snapshots" && options?.method === "POST") {
        return Promise.resolve({
          id: "v1",
          user_id: "u1",
          component_type: "property_value",
          liquidity_class: "illiquid",
          as_of_date: "2026-05-18",
          value: "1250000.00",
          currency: "SGD",
          source: "manual",
          notes: null,
          recurrence_days: null,
          reminder_date: null,
          created_at: "2026-05-18T00:00:00Z",
          updated_at: "2026-05-18T00:00:00Z",
        })
      }
      return Promise.resolve({ items: [], total: 0 } satisfies ManagedPositionListResponse)
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("AC16.15.4 renders loading and error retry states", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/assets/valuation-snapshots")) {
        return Promise.resolve(emptyValuations)
      }
      return Promise.reject(new Error("positions failed"))
    })

    render(<AssetsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("Failed to load positions")).not.toBeNull())
    fireEvent.click(screen.getByRole("button", { name: "Retry loading positions" }))
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("/api/assets/positions")))
    expect(mockedApiFetch.mock.calls.filter(([path]) => String(path).startsWith("/api/assets/positions"))).toHaveLength(2)
  })

  it("AC16.15.5 renders grouped positions and supports status filters", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/assets/valuation-snapshots")) {
        return Promise.resolve(emptyValuations)
      }
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

    fireEvent.click(screen.getByRole("tab", { name: "disposed" }))
    await waitFor(() => expect(screen.queryByText("TSLA")).not.toBeNull())
    expect(screen.queryByText("AAPL")).toBeNull()
    expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("status_filter=disposed"))
  })

  it("AC16.15.6 reconcile action calls API and shows toast summary", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({ items: [], total: 0 } satisfies ManagedPositionListResponse)
      .mockResolvedValueOnce(emptyValuations)
      .mockResolvedValueOnce({
        message: "done",
        created: 1,
        updated: 2,
        disposed: 0,
        skipped: 0,
        skipped_assets: [],
      } satisfies ReconcilePositionsResponse)
      .mockResolvedValueOnce({ items: [], total: 0 } satisfies ManagedPositionListResponse)
      .mockResolvedValueOnce(emptyValuations)

    render(<AssetsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("No positions found")).not.toBeNull())
    fireEvent.click(screen.getByRole("button", { name: "Reconcile Positions" }))

    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/assets/reconcile", { method: "POST" })
    })
    expect(showToastMock).toHaveBeenCalledWith("Reconciled 3 positions (1 created, 2 updated, 0 disposed)", "success")
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("/api/assets/positions")))
  })

  it("AC16.23.3 renders portfolio KPI cards when positions are loaded", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/assets/valuation-snapshots")) {
        return Promise.resolve(emptyValuations)
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
        {
          id: "p2",
          user_id: "u1",
          account_id: "acc1",
          account_name: "IBKR",
          asset_identifier: "TSLA",
          quantity: "5",
          cost_basis: "900",
          acquisition_date: "2025-03-01",
          disposal_date: "2025-11-01",
          status: "disposed",
          currency: "USD",
          created_at: "2025-03-01",
          updated_at: "2025-11-01",
        },
      ],
      total: 2,
      } satisfies ManagedPositionListResponse)
    })

    render(<AssetsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Total Positions")).toBeInTheDocument())
    expect(screen.getByText("2")).toBeInTheDocument()
    expect(screen.getByText("Active Holdings")).toBeInTheDocument()
    expect(screen.getByText("1")).toBeInTheDocument()
    expect(screen.getByText("Total Cost Basis")).toBeInTheDocument()
    expect(screen.getByText("Book value (no market price yet)")).toBeInTheDocument()
  })

  it("AC16.23.4 renders currency allocation breakdown when multiple currencies present", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/assets/valuation-snapshots")) {
        return Promise.resolve(emptyValuations)
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
        {
          id: "p3",
          user_id: "u1",
          account_id: "acc2",
          account_name: "MOOMOO",
          asset_identifier: "9988.HK",
          quantity: "100",
          cost_basis: "800",
          acquisition_date: "2025-06-01",
          disposal_date: null,
          status: "active",
          currency: "HKD",
          created_at: "2025-06-01",
          updated_at: "2025-06-02",
        },
      ],
      total: 2,
      } satisfies ManagedPositionListResponse)
    })

    render(<AssetsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Allocation by Currency")).toBeInTheDocument())
    expect(screen.getByText("USD")).toBeInTheDocument()
    expect(screen.getByText("HKD")).toBeInTheDocument()
  })

  it("shows warning toast when reconcile has skipped assets", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({ items: [], total: 0 } satisfies ManagedPositionListResponse)
      .mockResolvedValueOnce(emptyValuations)
      .mockResolvedValueOnce({
        message: "done",
        created: 1,
        updated: 0,
        disposed: 0,
        skipped: 2,
        skipped_assets: ["BTC", "ETH"],
      } satisfies ReconcilePositionsResponse)
      .mockResolvedValueOnce({ items: [], total: 0 } satisfies ManagedPositionListResponse)
      .mockResolvedValueOnce(emptyValuations)

    render(<AssetsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("No positions found")).not.toBeNull())
    fireEvent.click(screen.getByRole("button", { name: "Run Reconciliation" }))

    await waitFor(() => {
      expect(showToastMock).toHaveBeenCalledWith(
        expect.stringContaining("2 skipped"),
        "warning"
      )
    })
  })

  it("shows error toast when reconcile fails", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({ items: [], total: 0 } satisfies ManagedPositionListResponse)
      .mockResolvedValueOnce(emptyValuations)
      .mockRejectedValueOnce(new Error("server error"))

    render(<AssetsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.queryByText("No positions found")).not.toBeNull())
    fireEvent.click(screen.getByRole("button", { name: "Run Reconciliation" }))

    await waitFor(() => {
      expect(showToastMock).toHaveBeenCalledWith(
        expect.stringContaining("server error"),
        "error"
      )
    })
  })

  it("formats fractional quantities with decimal places", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/assets/valuation-snapshots")) {
        return Promise.resolve(emptyValuations)
      }
      return Promise.resolve({
      items: [
        {
          id: "p1",
          user_id: "u1",
          account_id: "acc1",
          account_name: "IBKR",
          asset_identifier: "BTC",
          quantity: "0.5",
          cost_basis: "15000",
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

    await waitFor(() => expect(screen.getByText("BTC")).toBeInTheDocument())
    expect(screen.getByText(/0\.50 units/)).toBeInTheDocument()
  })

  it("AC11.9.4 renders manual valuation snapshots and creates a new property valuation", async () => {
    mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/assets/valuation-snapshots" && options?.method === "POST") {
        return Promise.resolve({
          id: "v2",
          user_id: "u1",
          component_type: "property_value",
          liquidity_class: "illiquid",
          as_of_date: "2026-05-18",
          value: "1250000.00",
          currency: "SGD",
          source: "manual",
          notes: null,
          recurrence_days: null,
          reminder_date: null,
          created_at: "2026-05-18T00:00:00Z",
          updated_at: "2026-05-18T00:00:00Z",
        })
      }
      if (path.startsWith("/api/assets/valuation-snapshots")) {
        return Promise.resolve({
          items: [
            {
              id: "v1",
              user_id: "u1",
              component_type: "cpf_balance",
              liquidity_class: "restricted",
              as_of_date: "2026-05-01",
              value: "50000.00",
              currency: "SGD",
              source: "CPF portal",
              notes: null,
              recurrence_days: null,
              reminder_date: null,
              created_at: "2026-05-01T00:00:00Z",
              updated_at: "2026-05-01T00:00:00Z",
            },
          ],
          total: 1,
        } satisfies ManualValuationSnapshotListResponse)
      }
      return Promise.resolve({ items: [], total: 0 } satisfies ManagedPositionListResponse)
    })

    render(<AssetsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText(/CPF portal/)).toBeInTheDocument())
    expect(screen.getByText("Manual Valuations")).toBeInTheDocument()
    expect(screen.getAllByText("CPF Balance").length).toBeGreaterThan(0)
    expect(screen.getByText("Restricted")).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText("Valuation type"), { target: { value: "property_value" } })
    fireEvent.change(screen.getByLabelText("As of date"), { target: { value: "2026-05-18" } })
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "1250000.00" } })
    fireEvent.change(screen.getByLabelText("Currency"), { target: { value: "SGD" } })
    fireEvent.change(screen.getByLabelText("Source"), { target: { value: "broker portal" } })
    fireEvent.change(screen.getByLabelText("Notes"), { target: { value: "Audited manually" } })
    fireEvent.click(screen.getByRole("button", { name: "Add valuation" }))

    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/assets/valuation-snapshots",
        expect.objectContaining({ method: "POST" })
      )
    })
    expect(showToastMock).toHaveBeenCalledWith("Manual valuation saved", "success")
  })

  it("test_AC8_13_48 shows an error toast when manual valuation creation fails", async () => {
    mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/assets/valuation-snapshots" && options?.method === "POST") {
        return Promise.reject(new Error("valuation failed"))
      }
      if (path.startsWith("/api/assets/valuation-snapshots")) {
        return Promise.resolve(emptyValuations)
      }
      return Promise.resolve({ items: [], total: 0 } satisfies ManagedPositionListResponse)
    })

    render(<AssetsPage />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("Manual Valuations")).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "1250000.00" } })
    fireEvent.change(screen.getByLabelText("Currency"), { target: { value: "usd" } })
    fireEvent.change(screen.getByLabelText("Source"), { target: { value: "broker portal" } })
    fireEvent.change(screen.getByLabelText("Notes"), { target: { value: "Needs follow-up" } })
    fireEvent.click(screen.getByRole("button", { name: "Add valuation" }))

    await waitFor(() => {
      expect(showToastMock).toHaveBeenCalledWith("Failed to save valuation: valuation failed", "error")
    })
  })
})

import "@testing-library/jest-dom/vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { PerformanceCard } from "@/components/portfolio/PerformanceCard"
import { apiFetch } from "@/lib/api"
import type { PerformanceMetrics } from "@/lib/types"

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
  const TestWrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  TestWrapper.displayName = "PerformanceTestWrapper"
  return TestWrapper
}

const mockPerformance: PerformanceMetrics = {
  xirr: "12.50",
  time_weighted_return: "8.30",
  money_weighted_return: "-2.10",
}

describe("PerformanceCard", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
  })

  it("renders loading spinner while fetching", () => {
    mockedApiFetch.mockReturnValue(new Promise(() => {}))

    render(<PerformanceCard />, { wrapper: createWrapper() })

    expect(screen.getByText("Performance")).toBeInTheDocument()
    const spinner = document.querySelector(".animate-spin")
    expect(spinner).toBeTruthy()
  })

  it("renders error state when fetch fails", async () => {
    mockedApiFetch.mockRejectedValue(new Error("network error"))

    render(<PerformanceCard />, { wrapper: createWrapper() })

    await waitFor(() =>
      expect(screen.getByText("Unable to load performance metrics")).toBeInTheDocument(),
    )
  })

  it("renders three metrics with correct labels and formatted values", async () => {
    mockedApiFetch.mockResolvedValue(mockPerformance)

    render(<PerformanceCard />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("XIRR")).toBeInTheDocument())
    expect(screen.getByText("TWR")).toBeInTheDocument()
    expect(screen.getByText("MWR")).toBeInTheDocument()

    expect(screen.getByText("+12.50%")).toBeInTheDocument()
    expect(screen.getByText("+8.30%")).toBeInTheDocument()
    expect(screen.getByText("-2.10%")).toBeInTheDocument()
  })

  it("applies success color to positive values and error color to negative values", async () => {
    mockedApiFetch.mockResolvedValue(mockPerformance)

    render(<PerformanceCard />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("+12.50%")).toBeInTheDocument())

    const positiveEl = screen.getByText("+12.50%")
    expect(positiveEl.className).toContain("text-[var(--success)]")

    const negativeEl = screen.getByText("-2.10%")
    expect(negativeEl.className).toContain("text-[var(--error)]")
  })

  it("renders Performance Metrics header when data is loaded", async () => {
    mockedApiFetch.mockResolvedValue(mockPerformance)

    render(<PerformanceCard />, { wrapper: createWrapper() })

    await waitFor(() =>
      expect(screen.getByText("Performance Metrics")).toBeInTheDocument(),
    )
  })

  it("renders dash for NaN values", async () => {
    mockedApiFetch.mockResolvedValue({
      xirr: "not_a_number",
      time_weighted_return: "8.30",
      money_weighted_return: "0.00",
    })

    render(<PerformanceCard />, { wrapper: createWrapper() })

    await waitFor(() => expect(screen.getByText("\u2014")).toBeInTheDocument())
    expect(screen.getByText("+8.30%")).toBeInTheDocument()
    expect(screen.getByText("0.00%")).toBeInTheDocument()
  })
})

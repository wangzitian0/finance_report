import "@testing-library/jest-dom/vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AllocationChart } from "@/components/portfolio/AllocationChart"
import { apiFetch } from "@/lib/api"
import type { AllocationBreakdown } from "@/lib/types"

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
  TestWrapper.displayName = "AllocationTestWrapper"
  return TestWrapper
}

const mockAllocation: AllocationBreakdown[] = [
  { category: "Technology", value: "5000.00", percentage: "50.0", count: 3 },
  { category: "Healthcare", value: "3000.00", percentage: "30.0", count: 2 },
  { category: "Finance", value: "2000.00", percentage: "20.0", count: 1 },
]

describe("AllocationChart", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
  })

  it("renders loading spinner while fetching", () => {
    mockedApiFetch.mockReturnValue(new Promise(() => {}))

    render(<AllocationChart type="sector" title="Sector Allocation" />, {
      wrapper: createWrapper(),
    })

    expect(screen.getByText("Sector Allocation")).toBeInTheDocument()
    const spinner = document.querySelector(".animate-spin")
    expect(spinner).toBeTruthy()
  })

  it("renders error state when fetch fails", async () => {
    mockedApiFetch.mockRejectedValue(new Error("network error"))

    render(<AllocationChart type="sector" title="Sector Allocation" />, {
      wrapper: createWrapper(),
    })

    await waitFor(() =>
      expect(screen.getByText("Unable to load allocation data")).toBeInTheDocument(),
    )
  })

  it("renders empty state when data is empty array", async () => {
    mockedApiFetch.mockResolvedValue([])

    render(<AllocationChart type="geography" title="Geography Allocation" />, {
      wrapper: createWrapper(),
    })

    await waitFor(() =>
      expect(screen.getByText("No allocation data available")).toBeInTheDocument(),
    )
  })

  it("renders PieChart with center label matching type", async () => {
    mockedApiFetch.mockResolvedValue(mockAllocation)

    render(<AllocationChart type="sector" title="Sector Allocation" />, {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(screen.getAllByText("Technology").length).toBeGreaterThanOrEqual(1))

    const svg = screen.getByRole("img", { name: "Pie chart" })
    expect(svg).toBeInTheDocument()

    expect(screen.getByText("Sector")).toBeInTheDocument()
  })

  it("renders legend items with category, count, and percentage", async () => {
    mockedApiFetch.mockResolvedValue(mockAllocation)

    render(<AllocationChart type="sector" title="Sector Allocation" />, {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(screen.getAllByText("Technology").length).toBeGreaterThanOrEqual(1))

    expect(screen.getAllByText("Healthcare").length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText("Finance").length).toBeGreaterThanOrEqual(1)

    expect(screen.getByText("(3)")).toBeInTheDocument()
    expect(screen.getByText("(2)")).toBeInTheDocument()
    expect(screen.getByText("(1)")).toBeInTheDocument()

    expect(screen.getByText("50.0%")).toBeInTheDocument()
    expect(screen.getByText("30.0%")).toBeInTheDocument()
    expect(screen.getByText("20.0%")).toBeInTheDocument()
  })

  it("uses correct API endpoint based on type prop", async () => {
    mockedApiFetch.mockResolvedValue(mockAllocation)

    render(<AllocationChart type="asset-class" title="Asset Class" />, {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(screen.getAllByText("Technology").length).toBeGreaterThanOrEqual(1))

    expect(mockedApiFetch).toHaveBeenCalledWith("/api/portfolio/allocation/asset-class")
  })

  it("renders center label as 'Asset Class' for asset-class type", async () => {
    mockedApiFetch.mockResolvedValue(mockAllocation)

    render(<AllocationChart type="asset-class" title="Asset Class Allocation" />, {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(screen.getByText("Asset Class")).toBeInTheDocument())
  })

  it("renders center label as 'Geography' for geography type", async () => {
    mockedApiFetch.mockResolvedValue(mockAllocation)

    render(<AllocationChart type="geography" title="Geography Allocation" />, {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(screen.getByText("Geography")).toBeInTheDocument())
  })
})

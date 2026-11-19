import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AllocationChart } from "@/components/portfolio/PortfolioSummary";
import { apiOperation } from "@/lib/api";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const mockAllocation = [
  { category: "Technology", value: "5000.00", percentage: "50.0", count: 3 },
  { category: "Healthcare", value: "3000.00", percentage: "30.0", count: 2 },
  { category: "Finance", value: "2000.00", percentage: "20.0", count: 1 },
];

describe("AllocationChart", () => {
  const api = vi.mocked(apiOperation);
  beforeEach(() => { api.mockReset(); });

  it("renders loading, error, and empty states", async () => {
    api.mockReturnValueOnce(new Promise(() => {}));
    render(<AllocationChart type="sector" title="Sector Allocation" />);
    expect(screen.getByText("Sector Allocation")).toBeInTheDocument();
    expect(document.querySelector(".animate-spin")).toBeTruthy();

    api.mockRejectedValueOnce(new Error("network error"));
    render(<AllocationChart type="sector" title="S2" />);
    await waitFor(() => expect(screen.getByText("Unable to load allocation data")).toBeInTheDocument());

    api.mockResolvedValueOnce([]);
    render(<AllocationChart type="geography" title="Geography Allocation" />);
    await waitFor(() => expect(screen.getByText("No allocation data available")).toBeInTheDocument());
  });

  it.each([
    ["sector", "Sector Allocation", "Sector", "get_sector_allocation_portfolio_allocation_sector_get"],
    ["asset-class", "Asset Class Allocation", "Asset Class", "get_asset_class_allocation_portfolio_allocation_asset_class_get"],
    ["geography", "Geography Allocation", "Geography", "get_geography_allocation_portfolio_allocation_geography_get"],
  ] as const)("renders %s pie chart, legend, and endpoint", async (type, title, center, op) => {
    api.mockResolvedValue(mockAllocation);
    render(<AllocationChart type={type} title={title} />);
    await waitFor(() => expect(screen.getAllByText("Technology").length).toBeGreaterThanOrEqual(1));
    expect(screen.getByRole("img", { name: "Pie chart" })).toBeInTheDocument();
    expect(screen.getByText(center)).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(op);
    for (const t of ["Healthcare", "Finance", "(3)", "(2)", "(1)", "50.0%", "30.0%", "20.0%"]) {
      expect(screen.getAllByText(t).length).toBeGreaterThanOrEqual(1);
    }
  });
});

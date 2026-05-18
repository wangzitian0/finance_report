import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NetWorthTimeSeriesChart } from "@/components/charts/NetWorthTimeSeriesChart";
import { apiFetch } from "@/lib/api";
import type { NetWorthTimeSeriesResponse } from "@/lib/types";

vi.mock("echarts-for-react", () => ({
  default: () => <div role="img" aria-label="ECharts net worth line chart" />,
}));

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

describe("EPIC-005 / UI Gap Audit / Net Worth Time Series", () => {
  const mockedApiFetch = vi.mocked(apiFetch);

  beforeEach(() => {
    mockedApiFetch.mockReset();
  });

  it("AC5.7.2/AC5.7.6 mounts an ECharts-backed net worth line chart", async () => {
    mockedApiFetch.mockResolvedValue({
      currency: "SGD",
      granularity: "daily",
      points: [
        { date: "2026-05-01", total_assets: "1000.00", total_liabilities: "100.00", net_worth: "900.00", currency: "SGD" },
        { date: "2026-05-02", total_assets: "1100.00", total_liabilities: "100.00", net_worth: "1000.00", currency: "SGD" },
      ],
    } satisfies NetWorthTimeSeriesResponse);

    render(<NetWorthTimeSeriesChart />);

    await waitFor(() => expect(screen.getByTestId("net-worth-echarts")).toBeInTheDocument());
    expect(screen.getByRole("img", { name: "ECharts net worth line chart" })).toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("/api/reports/net-worth/timeseries"));
  });

  it("AC5.7.4 range selector toggles the from parameter and re-fetches", async () => {
    mockedApiFetch.mockResolvedValue({
      currency: "SGD",
      granularity: "daily",
      points: [
        { date: "2026-05-01", total_assets: "1000.00", total_liabilities: "100.00", net_worth: "900.00", currency: "SGD" },
        { date: "2026-05-02", total_assets: "1100.00", total_liabilities: "100.00", net_worth: "1000.00", currency: "SGD" },
      ],
    } satisfies NetWorthTimeSeriesResponse);

    render(<NetWorthTimeSeriesChart />);
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("tab", { name: "1M" }));

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(2));
    expect(String(mockedApiFetch.mock.calls[1][0])).toContain("granularity=daily");
    expect(String(mockedApiFetch.mock.calls[1][0])).toContain("from=");
  });

  it("AC5.7.5 renders an empty state when fewer than two points exist", async () => {
    mockedApiFetch.mockResolvedValue({
      currency: "SGD",
      granularity: "daily",
      points: [
        { date: "2026-05-01", total_assets: "1000.00", total_liabilities: "100.00", net_worth: "900.00", currency: "SGD" },
      ],
    } satisfies NetWorthTimeSeriesResponse);

    render(<NetWorthTimeSeriesChart />);

    await waitFor(() =>
      expect(screen.getByText("At least two net worth points are needed to draw a line.")).toBeInTheDocument(),
    );
  });
});

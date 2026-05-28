import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NetWorthTimeSeriesChart } from "@/components/charts/NetWorthTimeSeriesChart";
import { apiFetch } from "@/lib/api";
import type { NetWorthTimeSeriesResponse } from "@/lib/types";

let capturedChartOption: { tooltip?: { valueFormatter?: (value: number) => string } } | null = null;

vi.mock("echarts-for-react", () => ({
  default: (props: { option: { tooltip?: { valueFormatter?: (value: number) => string } } }) => {
    capturedChartOption = props.option;
    return <div role="img" aria-label="ECharts net worth line chart" />;
  },
}));

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

describe("EPIC-005 / UI Gap Audit / Net Worth Time Series", () => {
  const mockedApiFetch = vi.mocked(apiFetch);

  beforeEach(() => {
    mockedApiFetch.mockReset();
    capturedChartOption = null;
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
    expect(capturedChartOption?.tooltip?.valueFormatter?.(1234)).toContain("1,234.00");
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

    fireEvent.click(screen.getByRole("tab", { name: "All" }));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(3));
    expect(String(mockedApiFetch.mock.calls[2][0])).toContain("from=1970-01-01");
    expect(String(mockedApiFetch.mock.calls[2][0])).toContain("granularity=monthly");
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

  it("test_AC8_13_48 shows net worth history load failures", async () => {
    mockedApiFetch.mockRejectedValueOnce(new Error("history failed"));

    render(<NetWorthTimeSeriesChart />);

    expect(await screen.findByText("history failed")).toBeInTheDocument();
  });
});

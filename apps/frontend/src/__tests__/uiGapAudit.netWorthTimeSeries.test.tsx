import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NetWorthTimeSeriesChart } from "@/components/charts/NetWorthTimeSeriesChart";
import { apiOperation } from "@/lib/api-client";
import type { NetWorthTimeSeriesResponse } from "@/lib/types";

let capturedChartOption: { tooltip?: { valueFormatter?: (value: number) => string } } | null = null;

vi.mock("echarts-for-react", () => ({
  default: (props: { option: { tooltip?: { valueFormatter?: (value: number) => string } } }) => {
    capturedChartOption = props.option;
    return <div role="img" aria-label="ECharts net worth line chart" />;
  },
}));

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}));

const QUARTER = { from: "2026-04-01", to: "2026-06-30", includeRestricted: true } as const;

function createQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWithClient(ui: ReactElement, client: QueryClient = createQueryClient()) {
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const TWO_POINTS = {
  currency: "SGD",
  granularity: "daily",
  points: [
    { date: "2026-05-01", total_assets: "1000.00", total_liabilities: "100.00", net_worth: "900.00", currency: "SGD" },
    { date: "2026-05-02", total_assets: "1100.00", total_liabilities: "100.00", net_worth: "1000.00", currency: "SGD" },
  ],
} satisfies NetWorthTimeSeriesResponse;

describe("EPIC-005 / UI Gap Audit / Net Worth Time Series", () => {
  const mockedApiOperation = vi.mocked(apiOperation);

  beforeEach(() => {
    mockedApiOperation.mockReset();
    capturedChartOption = null;
  });

  // AC-reporting.fe-viz-reports.28 / AC-reporting.fe-viz-reports.31
  it("AC5.7.2/AC5.7.6 mounts an ECharts-backed net worth line chart", async () => {
    mockedApiOperation.mockResolvedValue({
      currency: "SGD",
      granularity: "daily",
      points: [
        { date: "2026-05-01", total_assets: "1000.00", total_liabilities: "100.00", net_worth: "900.00", currency: "SGD" },
        { date: "2026-05-02", total_assets: "1100.00", total_liabilities: "100.00", net_worth: "1000.00", currency: "SGD" },
      ],
    } satisfies NetWorthTimeSeriesResponse);

    renderWithClient(<NetWorthTimeSeriesChart {...QUARTER} />);

    await waitFor(() => expect(screen.getByTestId("net-worth-echarts")).toBeInTheDocument());
    expect(await screen.findByRole("img", { name: "ECharts net worth line chart" })).toBeInTheDocument();
    expect(capturedChartOption?.tooltip?.valueFormatter?.(1234)).toContain("1,234.00");
    expect(mockedApiOperation).toHaveBeenCalledWith("net_worth_timeseries_reports_net_worth_timeseries_get", expect.anything());
  });

  // AC-reporting.fe-viz-reports.29
  it("AC5.7.4 reads the period of the dimension bar and draws months for a period longer than one quarter", async () => {
    mockedApiOperation.mockResolvedValue(TWO_POINTS);

    const { rerender } = renderWithClient(<NetWorthTimeSeriesChart {...QUARTER} currency="USD" />);
    await waitFor(() => expect(mockedApiOperation).toHaveBeenCalledTimes(1));
    expect(mockedApiOperation).toHaveBeenLastCalledWith("net_worth_timeseries_reports_net_worth_timeseries_get", {
      query: { from: "2026-04-01", to: "2026-06-30", granularity: "daily", currency: "USD", include_restricted: true },
    });
    expect(screen.getByRole("heading", { name: "Daily net worth" })).toBeInTheDocument();
    expect(screen.queryByRole("tab")).toBeNull();

    rerender(
      <QueryClientProvider client={createQueryClient()}>
        <NetWorthTimeSeriesChart from="2025-07-01" to="2026-06-30" includeRestricted />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(mockedApiOperation).toHaveBeenCalledTimes(2));
    expect(mockedApiOperation).toHaveBeenLastCalledWith("net_worth_timeseries_reports_net_worth_timeseries_get", {
      query: { from: "2025-07-01", to: "2026-06-30", granularity: "monthly", currency: undefined, include_restricted: true },
    });
    expect(screen.getByRole("heading", { name: "Monthly net worth" })).toBeInTheDocument();
  });

  // AC-reporting.fe-viz-reports.30
  it("AC5.7.5 renders an empty state when fewer than two points exist", async () => {
    mockedApiOperation.mockResolvedValue({
      currency: "SGD",
      granularity: "daily",
      points: [
        { date: "2026-05-01", total_assets: "1000.00", total_liabilities: "100.00", net_worth: "900.00", currency: "SGD" },
      ],
    } satisfies NetWorthTimeSeriesResponse);

    renderWithClient(<NetWorthTimeSeriesChart {...QUARTER} />);

    await waitFor(() =>
      expect(screen.getByText("At least two net worth points are needed to draw a line.")).toBeInTheDocument(),
    );
  });

  it("test_AC8_13_48 shows net worth history load failures", async () => {
    mockedApiOperation.mockRejectedValueOnce(new Error("history failed"));

    renderWithClient(<NetWorthTimeSeriesChart {...QUARTER} />);

    expect(await screen.findByText("history failed")).toBeInTheDocument();
  });

  // AC-reporting.net-worth-scope.4
  it("#2645 requests the series in the restricted-holdings scope of the dimension bar", async () => {
    mockedApiOperation.mockResolvedValue(TWO_POINTS);
    const client = createQueryClient();

    const full = renderWithClient(<NetWorthTimeSeriesChart {...QUARTER} />, client);
    await waitFor(() => expect(mockedApiOperation).toHaveBeenCalledTimes(1));
    full.unmount();
    renderWithClient(<NetWorthTimeSeriesChart {...QUARTER} includeRestricted={false} />, client);
    await waitFor(() => expect(mockedApiOperation).toHaveBeenCalledTimes(2));

    expect(mockedApiOperation.mock.calls.map(([, request]) => (request as { query: { include_restricted: boolean } }).query.include_restricted)).toEqual([true, false]);
  });

  // AC-reporting.fe-viz-reports.34
  it("caches each period so a revisit within the stale time sends no request", async () => {
    mockedApiOperation.mockResolvedValue(TWO_POINTS);
    const client = createQueryClient();

    const first = renderWithClient(<NetWorthTimeSeriesChart {...QUARTER} />, client);
    await waitFor(() => expect(screen.getByTestId("net-worth-echarts")).toBeInTheDocument());
    expect(mockedApiOperation).toHaveBeenCalledTimes(1);

    first.unmount();
    renderWithClient(<NetWorthTimeSeriesChart {...QUARTER} />, client);
    await waitFor(() => expect(screen.getByTestId("net-worth-echarts")).toBeInTheDocument());

    expect(mockedApiOperation).toHaveBeenCalledTimes(1);
    expect(client.getQueryCache().findAll({ queryKey: ["report", "net-worth-timeseries", "2026-04-01", "2026-06-30", "daily"] })).toHaveLength(1);
  });
});

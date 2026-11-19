import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NetWorthTimeSeriesChart } from "@/components/reports/StatementPanels";
import { apiOperation } from "@/lib/api";
import type { NetWorthTimeSeriesResponse } from "@/lib/types";

let capturedChartOption: {
  tooltip?: { valueFormatter?: (value: number, dataIndex?: number) => string };
} | null = null;

vi.mock("echarts-for-react", () => ({
  default: (props: {
    option: { tooltip?: { valueFormatter?: (value: number, dataIndex?: number) => string } };
  }) => {
    capturedChartOption = props.option;
    return <div role="img" aria-label="ECharts net worth line chart" />;
  },
}));

vi.mock("@/lib/api", () => ({
  apiOperation: vi.fn(),
}));

const RANGE = { from: "2026-01-01", to: "2026-01-02", includeRestricted: true } as const;

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("NetWorthTimeSeriesChart FX warning display (#2915)", () => {
  const mockedApiOperation = vi.mocked(apiOperation);

  beforeEach(() => {
    mockedApiOperation.mockReset();
    capturedChartOption = null;
  });

  it("shows an amber FX warning banner and incomplete tooltip status when FX rates are missing", async () => {
    mockedApiOperation.mockResolvedValue({
      currency: "SGD",
      granularity: "daily",
      points: [
        {
          date: "2026-01-01",
          total_assets: "1000.00",
          total_liabilities: "0.00",
          net_worth: "1000.00",
          currency: "SGD",
          incomplete: true,
          missing_fx_currencies: ["USD"],
        },
        {
          date: "2026-01-02",
          total_assets: "1130.00",
          total_liabilities: "0.00",
          net_worth: "1130.00",
          currency: "SGD",
          incomplete: false,
          missing_fx_currencies: [],
        },
      ],
      fx_warnings: [
        {
          type: "missing_fx_rate_partial_skip",
          base_currency: "USD",
          quote_currency: "SGD",
          rate_date: "2026-01-01",
        },
      ],
    } satisfies NetWorthTimeSeriesResponse);

    renderWithClient(<NetWorthTimeSeriesChart {...RANGE} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/omitted/i);
    expect(alert).toHaveTextContent(/USD to SGD/i);
    expect(alert).toHaveTextContent(/2026-01-01/);
    expect(capturedChartOption?.tooltip?.valueFormatter?.(1000, 0)).toMatch(/incomplete/i);
    expect(capturedChartOption?.tooltip?.valueFormatter?.(1130, 1)).not.toMatch(/incomplete/i);
  });

  it("shows the warning banner when points are marked incomplete even without fx_warnings", async () => {
    mockedApiOperation.mockResolvedValue({
      currency: "SGD",
      granularity: "daily",
      points: [
        {
          date: "2026-01-01",
          total_assets: "1000.00",
          total_liabilities: "0.00",
          net_worth: "1000.00",
          currency: "SGD",
          incomplete: true,
          missing_fx_currencies: ["EUR"],
        },
        {
          date: "2026-01-02",
          total_assets: "1100.00",
          total_liabilities: "0.00",
          net_worth: "1100.00",
          currency: "SGD",
          incomplete: false,
          missing_fx_currencies: [],
        },
      ],
    } satisfies NetWorthTimeSeriesResponse);

    renderWithClient(<NetWorthTimeSeriesChart {...RANGE} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/EUR to SGD/i);
    expect(alert).toHaveTextContent(/2026-01-01/);
  });

  it("hides the FX warning banner when all points are complete and fx_warnings is empty", async () => {
    mockedApiOperation.mockResolvedValue({
      currency: "SGD",
      granularity: "daily",
      points: [
        {
          date: "2026-01-01",
          total_assets: "1130.00",
          total_liabilities: "0.00",
          net_worth: "1130.00",
          currency: "SGD",
          incomplete: false,
          missing_fx_currencies: [],
        },
        {
          date: "2026-01-02",
          total_assets: "1140.00",
          total_liabilities: "0.00",
          net_worth: "1140.00",
          currency: "SGD",
          incomplete: false,
          missing_fx_currencies: [],
        },
      ],
      fx_warnings: [],
    } satisfies NetWorthTimeSeriesResponse);

    renderWithClient(<NetWorthTimeSeriesChart {...RANGE} />);

    await waitFor(() => expect(screen.getByTestId("net-worth-echarts")).toBeInTheDocument());
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

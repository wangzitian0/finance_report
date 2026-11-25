import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NetWorthTimeSeriesChart } from "@/components/reports/StatementPanels";
import { apiOperation } from "@/lib/api";
import type { NetWorthTimeSeriesResponse } from "@/lib/types";

type Opt = { tooltip?: { valueFormatter?: (v: number, i?: number) => string } };
let opt: Opt | null = null;
vi.mock("echarts-for-react", () => ({
  default: ({ option }: { option: Opt }) => {
    opt = option;
    return <div role="img" aria-label="ECharts net worth line chart" />;
  },
}));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));

const api = vi.mocked(apiOperation),
  S = "SGD",
  R = /incomplete/i,
  CH = "ECharts net worth line chart";
const pt = (
  date: string,
  v: string,
  incomplete = false,
  missing_fx_currencies: string[] = [],
) => ({
  date,
  total_assets: v,
  total_liabilities: "0.00",
  net_worth: v,
  currency: S,
  incomplete,
  missing_fx_currencies,
});
const go = (
  points: ReturnType<typeof pt>[],
  fx_warnings?: NetWorthTimeSeriesResponse["fx_warnings"],
) => {
  api.mockResolvedValue({
    currency: S,
    granularity: "daily",
    points,
    ...(fx_warnings ? { fx_warnings } : {}),
  } satisfies NetWorthTimeSeriesResponse);
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <NetWorthTimeSeriesChart
        from="2026-01-01"
        to="2026-01-02"
        includeRestricted
      />
    </QueryClientProvider>,
  );
};

describe("NetWorthTimeSeriesChart FX warning display (#2915)", () => {
  beforeEach(() => {
    api.mockReset();
    opt = null;
  });

  it("shows amber FX warning banner and incomplete tooltip when FX missing", async () => {
    go(
      [pt("2026-01-01", "1000.00", true, ["USD"]), pt("2026-01-02", "1130.00")],
      [
        {
          type: "missing_fx_rate_partial_skip",
          base_currency: "USD",
          quote_currency: S,
          rate_date: "2026-01-01",
        },
        { message: "Custom FX gap" },
        { base_currency: "GBP", quote_currency: S },
        { rate_date: "2026-01-02" },
      ],
    );
    const alert = await screen.findByRole("alert");
    for (const rx of [
      /omitted/i,
      /USD to SGD/i,
      /2026-01-01/,
      /Custom FX gap/,
      /GBP to SGD/,
      /Missing FX rate on 2026-01-02/,
    ])
      expect(alert).toHaveTextContent(rx);
    await screen.findByRole("img", { name: CH });
    expect(opt?.tooltip?.valueFormatter?.(1000, 0)).toMatch(R);
    expect(opt?.tooltip?.valueFormatter?.(1130, 1)).not.toMatch(R);
  });

  it("shows warning banner for incomplete points even without fx_warnings", async () => {
    go([
      pt("2026-01-01", "1000.00", true, ["EUR"]),
      pt("2026-01-02", "1100.00", true),
    ]);
    const alert = await screen.findByRole("alert");
    for (const rx of [
      /EUR to SGD/i,
      /2026-01-01/,
      /Missing FX rate on 2026-01-02/,
    ])
      expect(alert).toHaveTextContent(rx);
    await screen.findByRole("img", { name: CH });
    expect(opt?.tooltip?.valueFormatter?.(1100, 1)).toMatch(/\(incomplete\)$/);
  });

  it("hides FX warning banner when all points complete", async () => {
    go([pt("2026-01-01", "1130.00"), pt("2026-01-02", "1140.00")], []);
    await waitFor(() =>
      expect(screen.getByTestId("net-worth-echarts")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

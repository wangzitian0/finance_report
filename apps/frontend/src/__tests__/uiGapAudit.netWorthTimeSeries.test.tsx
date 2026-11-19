import { render as R } from "@testing-library/react";
import { beforeEach, describe, it, vi } from "vitest";
import { NetWorthTimeSeriesChart } from "@/components/reports/StatementPanels";
import { apiOperation } from "@/lib/api";
import * as X from "./helpers/shellTestFixtures";

let opt: { tooltip?: { valueFormatter?: (v: number) => string } } | null = null;
vi.mock("echarts-for-react", () => ({ default: (p: { option: { tooltip?: { valueFormatter?: (v: number) => string } } }) => { opt = p.option; return <div role="img" aria-label="ECharts net worth line chart" />; } }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation), Q = { from: "2026-04-01", to: "2026-06-30", includeRestricted: true } as const;

describe("Net Worth Time Series", () => {
  beforeEach(() => { api.mockReset(); opt = null; });
  it("mounts ECharts, granularity, empty/error", () =>
    X.runNetWorthSeriesStates(api, (p) => R(<NetWorthTimeSeriesChart {...(p as typeof Q)} />), (p) => <NetWorthTimeSeriesChart {...(p as typeof Q)} />, () => opt));
  it("scopes cache & reuses warm cache", () => X.runNetWorthCacheScope(api, (inc) => <NetWorthTimeSeriesChart {...Q} includeRestricted={inc} />));
});
// AC-reporting.fe-viz-reports.28-31 AC-reporting.fe-viz-reports.34 AC-reporting.net-worth-scope.4

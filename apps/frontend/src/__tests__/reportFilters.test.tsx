import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { coverageNote, ReportDimensionBar } from "@/components/reports/ReportShell";
import { useReportFilters } from "@/hooks/useReportFilters";
import { apiOperation } from "@/lib/api";
import { setTestUrl, testUrl } from "./helpers/nextNavigation";
import * as F from "./helpers/packageTestFixtures";

vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
vi.mock("next/link", async () => ({ default: (await import("./helpers/packageTestFixtures")).mockLink }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const Bar = ({ showScope = false }: { showScope?: boolean }) => <ReportDimensionBar filters={useReportFilters()} showScope={showScope} />;

describe("ReportDimensionBar", () => {
  const api = vi.mocked(apiOperation);
  beforeEach(() => { api.mockReset(); F.mockFilterBarApi(api); setTestUrl("/reports?tab=cash-flow&period=1M&end=2026-01-31"); });

  it("AC-reporting.fe-period-cockpit.2 sets presets, steps periods, and configures custom periods via URL", () => F.assertFilterPresetsAndCustom(api, Bar));
  it("AC-reporting.fe-period-cockpit.7 bounds default view, disables controls while loading coverage, and formats coverageNote", () => F.assertFilterCoverage(api, Bar, coverageNote));

  it("AC5.34.2 syncs base currency, unknown URL currency, and restricted scope", async () => {
    const view = render(<Bar showScope />);
    const select = screen.getByRole("combobox", { name: "Reporting currency" });
    expect(await screen.findByRole("option", { name: "USD" })).toBeInTheDocument();
    expect(await screen.findByDisplayValue("EUR")).toBe(select);
    fireEvent.change(select, { target: { value: "USD" } });
    expect(testUrl()).toBe("/reports?tab=cash-flow&period=1M&end=2026-01-31&currency=USD");
    expect(F.lbl("Include restricted holdings")).toBeChecked(); F.clkLbl("Include restricted holdings");
    expect(testUrl()).toContain("include_restricted=false"); expect(F.lbl("Include restricted holdings")).not.toBeChecked(); view.unmount();
    setTestUrl("/reports?currency=JPY"); render(<Bar />);
    expect(screen.getByRole("combobox", { name: "Reporting currency" })).toHaveValue("JPY");
  });
}); // AC-reporting.fe-viz-reports.18 AC-reporting.fe-viz-reports.19

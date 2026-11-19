import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ReportsPage from "@/app/(main)/reports/page";
import { apiOperation, apiOperationDownload } from "@/lib/api";
import { setTestUrl } from "./helpers/nextNavigation";
import * as F from "./helpers/packageTestFixtures";

vi.mock("next/link", async () => ({ default: (await import("./helpers/packageTestFixtures")).mockLink }));
vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
vi.mock("@/hooks/useBaseCurrency", () => ({ useBaseCurrency: () => ({ baseCurrency: "SGD", loading: false }) }));
vi.mock("@/components/charts/BarChart", () => ({ BarChart: () => <div>BarChartMock</div> }));
vi.mock("@/hooks/useCurrencies", () => ({ useCurrencies: () => ({ currencies: ["SGD", "USD"] }) }));
vi.mock("@/lib/api", () => ({ API_URL: "http://localhost:8000", apiOperation: vi.fn(), apiOperationDownload: vi.fn() }));

describe("IncomeStatementPage", () => {
  const api = vi.mocked(apiOperation), dl = vi.mocked(apiOperationDownload);
  beforeEach(() => { dl.mockReset(); api.mockReset(); setTestUrl("/reports?tab=income-statement"); });

  it("AC16.14.4 renders loading and error retry states", () => F.assertReportLoadingError(api, ReportsPage, "Loading income statement", "income failed"));
  it("AC16.14.5 / test_AC8_13_48 renders string KPI cards, FX warning, provenance, and categories", () => F.assertIsFilled(api, ReportsPage));
  it("AC16.14.6 AC16.14.10 AC16.14.11 / test_AC8_13_48 handles tags, empty states, account type, and dates", () => F.assertIsTagsDates(api, ReportsPage));

  it("AC22.3.4 opens source drill-down from category name or dotted amount", async () => {
    api.mockImplementation(((op: string) => Promise.resolve(op === "account_lineage_reports_account_lineage_get" ? F.IS_LINEAGE : F.IS_FILLED())) as never);
    render(<ReportsPage />);
    await F.see("Salary");
    expect(F.btn("View source transactions for Rent")).toHaveClass("decoration-dotted");
    await F.assertLineageTriggers(["View source transactions for Rent", "Salary", "View source transactions for Salary"], "January payroll");
  });
}); // AC-reporting.fe-report-surfaces.13 AC-reporting.fe-report-surfaces.14 AC-reporting.fe-report-surfaces.15

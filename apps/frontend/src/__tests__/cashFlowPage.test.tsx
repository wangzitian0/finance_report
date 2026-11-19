import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ReportsPage from "@/app/(main)/reports/page";
import { apiOperation, apiOperationDownload } from "@/lib/api";
import { setTestUrl } from "./helpers/nextNavigation";
import * as F from "./helpers/packageTestFixtures";

vi.mock("next/link", async () => ({ default: (await import("./helpers/packageTestFixtures")).mockLink }));
vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
vi.mock("@/hooks/useBaseCurrency", () => ({ useBaseCurrency: () => ({ baseCurrency: "SGD", loading: false }) }));
vi.mock("@/components/charts/SankeyChart", () => ({ SankeyChart: () => <div>SankeyChartMock</div> }));
vi.mock("@/hooks/useCurrencies", () => ({ useCurrencies: () => ({ currencies: ["SGD", "USD", "EUR"], loading: false }) }));
vi.mock("@/lib/api", () => ({ API_URL: "http://localhost:8000", apiOperation: vi.fn(), apiOperationDownload: vi.fn() }));

describe("CashFlowPage", () => {
  const api = vi.mocked(apiOperation), dl = vi.mocked(apiOperationDownload);
  beforeEach(() => { dl.mockReset(); api.mockReset(); setTestUrl("/reports?tab=cash-flow"); F.stubUrlAssign(); });

  it("AC16.14.7 renders loading and error retry states", () => F.assertReportLoadingError(api, ReportsPage, "Loading cash flow", "cashflow failed", 10, "cash_flow_reports_cash_flow_get"));
  it("AC16.14.8 AC16.14.9 / test_AC8_13_48 renders summary, activity sections, FX warning, and sankey", () => F.assertCfFullAndSankey(api, ReportsPage));
  it("AC22.7.1 AC-reporting.fe-fetch-budget.8 drills account lineage and lazy-loads/pages line events", () => F.assertCfLineageAndPaging(api, ReportsPage));
  it("AC5.17.1 AC16.14.10 / test_AC8_13_48 exports CSV and refetches on currency and period changes", () => F.assertCfExportAndPeriod(api, dl, ReportsPage));

  it.each(F.CF_RECON_CASES)("AC22.7.3 renders cash reconciliation proof/mismatch disclosures", async (overrides, hasTexts, msgRegex, absentTexts) => {
    api.mockResolvedValue(F.makeCashFlow({ start_date: "2026-01-01", end_date: "2026-01-31", ...overrides }) as never);
    render(<ReportsPage />);
    const rec = await F.fLbl("Cash reconciliation");
    for (const t of hasTexts) expect(rec).toHaveTextContent(t);
    for (const t of absentTexts) expect(rec).not.toHaveTextContent(t);
    expect(F.txt(msgRegex)).toBeInTheDocument();
  });
}); // AC-reporting.fe-ia-reports.10 AC-reporting.fe-ia-reports.12 AC-reporting.fe-report-surfaces.16 AC-reporting.fe-report-surfaces.17 AC-reporting.fe-report-surfaces.18 AC-reporting.report-integrity.3

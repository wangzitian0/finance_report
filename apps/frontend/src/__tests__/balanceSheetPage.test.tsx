import { fireEvent, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ReportsPage from "@/app/(main)/reports/page";
import { apiOperation, apiOperationDownload } from "@/lib/api";
import { setTestUrl } from "./helpers/nextNavigation";
import * as F from "./helpers/packageTestFixtures";

vi.mock("next/link", async () => ({
  default: (await import("./helpers/packageTestFixtures")).mockLink,
}));
vi.mock(
  "next/navigation",
  async () => (await import("./helpers/nextNavigation")).nextNavigationMock,
);
vi.mock("@/hooks/useCurrencies", () => ({
  useCurrencies: () => ({ currencies: ["SGD", "USD"] }),
}));
vi.mock("@/hooks/useBaseCurrency", () => ({
  useBaseCurrency: () => ({ baseCurrency: "SGD", loading: false }),
}));
vi.mock("@/lib/api", () => ({
  API_URL: "http://localhost:8000",
  apiOperation: vi.fn(),
  apiOperationDownload: vi.fn(),
}));
const api = vi.mocked(apiOperation);

describe("BalanceSheetPage", () => {
  beforeEach(() => {
    vi.mocked(apiOperationDownload).mockReset();
    api.mockReset();
    setTestUrl("/reports?tab=balance-sheet");
  });

  it("AC16.14.1 renders loading and error retry states", () =>
    F.assertReportLoadingError(
      api,
      ReportsPage,
      "Loading balance sheet",
      "balance failed",
      12,
    ));
  it("AC16.14.2 AC8.13.42 / test_AC8_13_48 renders vector totals, provenance, scope, and refetches by date", () =>
    F.assertBsVectorAndDate(api, ReportsPage));
  it("#2645 renders valuation equity line and excluded holdings with FX warnings", () =>
    F.assertBsValuationAndExcluded(api, ReportsPage));
  it("AC-reporting.2728.2 AC16.14.3 #1486 renders transit transfers, tree collapse, opening warning, CTA, and equation detail", () =>
    F.assertBsTransitCollapseCta(api, ReportsPage));

  it("AC-reporting.2728.3 AC-reporting.2654.2 opens lineage from account/amount and routes manual valuations to /portfolio", async () => {
    api.mockImplementation(((op: string) =>
      Promise.resolve(
        op === "account_lineage_reports_account_lineage_get"
          ? F.BS_LINEAGE_RESP
          : F.BS_LINEAGE_ASSETS(),
      )) as never);
    render(<ReportsPage />);
    const valLink = await F.fLnk(
      "Valuation: CPF Ordinary Account (cpf balance)",
    );
    expect(valLink).toHaveAttribute("href", "/portfolio?panel=evidence");
    const amtLink = F.lnk(
      "View valuation evidence for Valuation: CPF Ordinary Account (cpf balance)",
    );
    expect(amtLink).toHaveAttribute("href", "/portfolio?panel=evidence");
    fireEvent.click(valLink);
    fireEvent.click(amtLink);
    expect(
      api.mock.calls.filter(
        ([id]) => id === "account_lineage_reports_account_lineage_get",
      ),
    ).toEqual([]);
    const amtBtn = F.btn("View source transactions for Cash");
    expect(amtBtn).toHaveClass("decoration-dotted");
    await F.assertLineageTriggers([amtBtn, F.btn("Cash")], "Opening deposit");
  });
}); // AC-reporting.api-vectors.2 AC-reporting.fe-report-surfaces.10 AC-reporting.fe-report-surfaces.11 AC-reporting.fe-report-surfaces.12 AC-reporting.fe-viz-reports.10 AC-reporting.fe-viz-reports.8 AC-reporting.fe-viz-reports.9 AC-reporting.net-worth-scope.6 AC-reporting.net-worth-scope.7
